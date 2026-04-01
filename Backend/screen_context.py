# #!/usr/bin/env python3
# """
# screen_context.py — Per-session screen context store.

# Holds the latest vision analysis result for each active session.
# Thread-safe, in-memory, per-session — mirrors the existing isolated session model.

# Usage from other modules:
#     import screen_context as ctx_store

#     ctx_store.get_or_create(session_id)
#     ctx_store.update(session_id, last_summary="...", screen_type="code", ...)
#     snippet = ctx_store.build_voice_injection(session_id)
#     if ctx_store.has_new_context(session_id):
#         ...
#     ctx_store.mark_injected(session_id)
#     ctx_store.remove(session_id)
# """

# import threading
# import time
# from dataclasses import dataclass, field
# from typing import Optional


# # ── Context dataclass ─────────────────────────────────────────────────────────

# @dataclass
# class ScreenContext:
#     session_id: str

#     # Latest analysis results
#     last_summary: str = ""
#     last_seen_at: float = 0.0
#     screen_type: str = "unknown"       # code | document | slide | browser | video | empty | unknown
#     key_entities: list = field(default_factory=list)
#     raw_text_excerpt: str = ""
#     confidence: float = 0.0

#     # Injection tracking — used by realtime.py to avoid re-injecting the same context
#     changed_recently: bool = False
#     last_injected_summary: str = ""
#     analysis_count: int = 0


# # ── Global in-memory store ────────────────────────────────────────────────────

# _contexts: dict[str, ScreenContext] = {}
# _lock = threading.Lock()

# # Context older than this (seconds) is treated as stale and not injected
# CONTEXT_STALE_AFTER_SECONDS = 45


# # ── CRUD helpers ──────────────────────────────────────────────────────────────

# def get_or_create(session_id: str) -> ScreenContext:
#     """Get existing context or create a fresh one for this session."""
#     with _lock:
#         if session_id not in _contexts:
#             _contexts[session_id] = ScreenContext(session_id=session_id)
#         return _contexts[session_id]


# def update(session_id: str, **kwargs):
#     """Update one or more fields on the context for a session."""
#     with _lock:
#         ctx = _contexts.get(session_id)
#         if ctx:
#             for k, v in kwargs.items():
#                 if hasattr(ctx, k):
#                     setattr(ctx, k, v)


# def get_context(session_id: str) -> Optional[ScreenContext]:
#     """Return the current context object, or None if not found."""
#     with _lock:
#         return _contexts.get(session_id)


# def remove(session_id: str):
#     """Remove context when a session ends (called by vision_worker cleanup)."""
#     with _lock:
#         _contexts.pop(session_id, None)


# def mark_injected(session_id: str):
#     """
#     Call this after realtime.py successfully pushes the context into the LLM session.
#     Clears changed_recently so we don't re-inject the same content.
#     """
#     with _lock:
#         ctx = _contexts.get(session_id)
#         if ctx:
#             ctx.changed_recently = False
#             ctx.last_injected_summary = ctx.last_summary


# def has_new_context(session_id: str) -> bool:
#     """
#     True if the screen changed since the last injection AND
#     the new summary is different from what was last injected.
#     Used by realtime.py to decide whether to send a session.update.
#     """
#     with _lock:
#         ctx = _contexts.get(session_id)
#         if not ctx:
#             return False
#         return ctx.changed_recently and (ctx.last_summary != ctx.last_injected_summary)


# # ── Voice injection builder ───────────────────────────────────────────────────

# def build_voice_injection(session_id: str) -> str:
#     """
#     Returns a text block to append to the GPT Realtime session instructions.
#     Returns empty string if:
#       - No context exists for this session
#       - Context is stale (older than CONTEXT_STALE_AFTER_SECONDS)
#       - Confidence is too low to be reliable
#       - Screen type is empty or unknown (just the Meet UI — nothing to reference)

#     The returned block tells the LLM what is currently on screen and how to use it
#     naturally in the voice interview. It is appended to the original system prompt
#     in realtime.py before sending session.update.
#     """
#     ctx = get_context(session_id)
#     if not ctx or not ctx.last_summary:
#         return ""

#     # Stale context check
#     age = time.time() - ctx.last_seen_at
#     if age > CONTEXT_STALE_AFTER_SECONDS:
#         return ""

#     # Low-confidence or non-content screen — skip injection
#     if ctx.confidence < 0.4 or ctx.screen_type in ("empty", "unknown", "video"):
#         return ""

#     lines = [
#         "\n\n--- CURRENT SCREEN CONTEXT (live, updated automatically) ---",
#         f"The candidate's screen is currently showing: {ctx.last_summary}",
#     ]

#     # Screen-type-specific coaching for the LLM
#     type_hints = {
#         "code": (
#             "The candidate is sharing code. "
#             "You may ask about their implementation, logic, naming choices, or potential bugs. "
#             "Reference the code naturally — e.g. 'I can see you have a function here...'"
#         ),
#         "document": (
#             "The candidate is sharing a document or PDF. "
#             "You may reference its content and ask them to explain specific sections."
#         ),
#         "slide": (
#             "The candidate is showing a presentation slide. "
#             "Ask them to walk you through it or elaborate on specific points."
#         ),
#         "browser": (
#             "The candidate is sharing their browser. "
#             "Feel free to reference what is visible on screen."
#         ),
#     }
#     hint = type_hints.get(ctx.screen_type)
#     if hint:
#         lines.append(hint)

#     if ctx.raw_text_excerpt:
#         lines.append(f"Key visible text on screen: \"{ctx.raw_text_excerpt[:200]}\"")

#     if ctx.key_entities:
#         lines.append(f"Notable items visible: {', '.join(ctx.key_entities[:5])}")

#     lines += [
#         "Use this context naturally in your next response only if it is relevant.",
#         "Do NOT robotically announce 'I can see your screen' — weave it in naturally.",
#         "--- END SCREEN CONTEXT ---",
#     ]

#     return "\n".join(lines)








































#!/usr/bin/env python3
"""
screen_context.py — Per-session screen context store (v2 — Live Event support).

Holds the latest vision analysis result for each active session.
Thread-safe, in-memory, per-session — mirrors the existing isolated session model.

v2 additions:
  - `has_live_event` flag: signals realtime.py to inject via conversation.item.create
  - `live_event_text`: pre-formatted text for the conversation item
  - `prev_screen_type` / `prev_confidence`: track previous state for change detection
  - `is_significant_change()`: decides whether a new analysis warrants a live event
  - `build_live_event_text()`: builds the [SCREEN EVENT] string for conversation history

Two-tier injection model used by realtime.py:

  Tier 1 — Live Event (conversation.item.create)
    Triggered by: significant screen change (type changed, sharing started/stopped)
    Effect: injected into conversation HISTORY — model treats it as something that
            happened in the session. Responded to on candidate's next speech turn.

  Tier 2 — Background (session.update instructions)
    Triggered by: any new context, even minor updates
    Effect: silently updates background system prompt. Persists across all turns.
            Model may or may not reference it explicitly.

Significant change rules (trigger Tier 1):
  1. Candidate started sharing  — confidence jumps from <0.5 to ≥0.8 into a content type
  2. Candidate stopped sharing  — was content type, now empty/unknown with conf<0.3
  3. Screen type changed        — e.g. code→slide, slide→document (both high confidence)
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ── Context dataclass ─────────────────────────────────────────────────────────

@dataclass
class ScreenContext:
    session_id: str

    # Latest analysis results
    last_summary: str = ""
    last_seen_at: float = 0.0
    screen_type: str = "unknown"       # code | document | slide | browser | video | empty | unknown
    key_entities: list = field(default_factory=list)
    raw_text_excerpt: str = ""
    confidence: float = 0.0

    # Previous state — needed by is_significant_change()
    prev_screen_type: str = "unknown"
    prev_confidence: float = 0.0

    # Tier 2: Background injection (session.update)
    changed_recently: bool = False
    last_injected_summary: str = ""

    # Tier 1: Live event injection (conversation.item.create)
    has_live_event: bool = False
    live_event_text: str = ""

    analysis_count: int = 0


# ── Global in-memory store ────────────────────────────────────────────────────

_contexts: dict[str, ScreenContext] = {}
_lock = threading.Lock()

# Context older than this (seconds) is treated as stale — not injected
CONTEXT_STALE_AFTER_SECONDS = 45

# Screen types that represent actual shared content (not just Meet UI / video grid)
CONTENT_TYPES = {"code", "document", "slide", "browser"}


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_or_create(session_id: str) -> ScreenContext:
    """Get existing context or create a fresh one for this session."""
    with _lock:
        if session_id not in _contexts:
            _contexts[session_id] = ScreenContext(session_id=session_id)
        return _contexts[session_id]


def update(session_id: str, **kwargs):
    """
    Update one or more fields on the context for a session.
    Automatically saves previous screen_type and confidence before overwriting,
    so is_significant_change() can compare old vs new state.
    """
    with _lock:
        ctx = _contexts.get(session_id)
        if not ctx:
            return
        # Capture prev state before overwriting type/confidence
        if "screen_type" in kwargs:
            ctx.prev_screen_type = ctx.screen_type
            ctx.prev_confidence  = ctx.confidence
        for k, v in kwargs.items():
            if hasattr(ctx, k):
                setattr(ctx, k, v)


def get_context(session_id: str) -> Optional[ScreenContext]:
    """Return the current context object, or None if not found."""
    with _lock:
        return _contexts.get(session_id)


def remove(session_id: str):
    """Remove context when a session ends (called by vision_worker cleanup)."""
    with _lock:
        _contexts.pop(session_id, None)


# ── Significant change detection ──────────────────────────────────────────────

def is_significant_change(
    ctx: ScreenContext,
    new_type: str,
    new_confidence: float,
) -> Tuple[bool, str]:
    """
    Determines whether a new vision analysis result is significant enough to
    warrant a Tier 1 live event (conversation.item.create in realtime.py).

    Args:
        ctx:            Current context state BEFORE this update is applied.
        new_type:       Screen type from the latest analysis.
        new_confidence: Confidence score from the latest analysis.

    Returns:
        (is_significant: bool, reason: str)
        reason is a short string used for logging and for build_live_event_text().

    Rules evaluated in priority order:
      1. sharing_started  — was idle (<0.5 conf), now high-conf content type
      2. sharing_stopped  — was active content, now empty/unknown low-conf
      3. type_changed     — meaningful switch between content categories
    """
    old_type = ctx.screen_type
    old_conf = ctx.confidence

    # Rule 1: Candidate started sharing their screen
    if old_conf < 0.5 and new_confidence >= 0.8 and new_type in CONTENT_TYPES:
        return True, "sharing_started"

    # Rule 2: Candidate stopped sharing their screen
    if (old_type in CONTENT_TYPES and old_conf >= 0.6
            and new_type in ("empty", "unknown") and new_confidence < 0.3):
        return True, "sharing_stopped"

    # Rule 3: Screen type changed between content categories
    if (old_type in CONTENT_TYPES and new_type in CONTENT_TYPES
            and old_type != new_type and new_confidence >= 0.7):
        return True, f"type_changed_{old_type}_to_{new_type}"

    return False, ""


# ── Live event (Tier 1) ───────────────────────────────────────────────────────

def mark_as_live_event(session_id: str, event_text: str):
    """
    Called by vision_worker when is_significant_change() returns True.
    Stores the [SCREEN EVENT] text for realtime.py to pick up and send
    via conversation.item.create.
    """
    with _lock:
        ctx = _contexts.get(session_id)
        if ctx:
            ctx.has_live_event   = True
            ctx.live_event_text  = event_text


def get_live_event(session_id: str) -> Tuple[bool, str]:
    """Returns (has_live_event, live_event_text) without consuming the event."""
    with _lock:
        ctx = _contexts.get(session_id)
        if ctx:
            return ctx.has_live_event, ctx.live_event_text
        return False, ""


def mark_live_event_consumed(session_id: str):
    """
    Called by realtime.py after conversation.item.create is sent successfully.
    Clears the live event so it is not sent again.
    """
    with _lock:
        ctx = _contexts.get(session_id)
        if ctx:
            ctx.has_live_event  = False
            ctx.live_event_text = ""


# ── Background context (Tier 2) ───────────────────────────────────────────────

def has_new_context(session_id: str) -> bool:
    """
    True if the screen changed since the last background injection AND
    the new summary differs from what was last injected.
    Used by realtime.py to decide whether to send session.update.
    """
    with _lock:
        ctx = _contexts.get(session_id)
        if not ctx:
            return False
        return ctx.changed_recently and (ctx.last_summary != ctx.last_injected_summary)


def mark_injected(session_id: str):
    """Called after realtime.py sends session.update. Clears changed_recently."""
    with _lock:
        ctx = _contexts.get(session_id)
        if ctx:
            ctx.changed_recently      = False
            ctx.last_injected_summary = ctx.last_summary


# ── Text builders ─────────────────────────────────────────────────────────────

def build_live_event_text(
    summary: str,
    screen_type: str,
    key_entities: list,
    raw_text_excerpt: str,
    reason: str,
) -> str:
    """
    Builds the [SCREEN EVENT] text for conversation.item.create (Tier 1).

    This text lands in conversation HISTORY. The model sees it as a live
    observation that occurred during the session — not background wallpaper.
    Keep it concise: summary + key details + one action hint.
    """
    # Stopped sharing — simple one-liner
    if reason == "sharing_stopped":
        return "[SCREEN EVENT] The candidate has stopped sharing their screen. Continue the interview by voice."

    lines = [f"[SCREEN EVENT] {summary}"]

    if screen_type in CONTENT_TYPES and key_entities:
        lines.append(f"Visible items: {', '.join(key_entities[:5])}")

    if raw_text_excerpt:
        lines.append(f'Key text on screen: "{raw_text_excerpt[:150]}"')

    action_hints = {
        "code":     "You can see their code — ask about it naturally in your next response.",
        "document": "You can see a document — reference its content in your next response.",
        "slide":    "You can see a presentation slide — ask them to walk you through it.",
        "browser":  "You can see their browser — reference what is visible naturally.",
    }
    hint = action_hints.get(screen_type)
    if hint:
        lines.append(hint)

    return "\n".join(lines)


def build_voice_injection(session_id: str) -> str:
    """
    Builds the text block appended to system prompt instructions for Tier 2 session.update.
    Returns empty string if context is stale, low-confidence, or has no content type.
    """
    ctx = get_context(session_id)
    if not ctx or not ctx.last_summary:
        return ""

    if time.time() - ctx.last_seen_at > CONTEXT_STALE_AFTER_SECONDS:
        return ""

    if ctx.confidence < 0.5 or ctx.screen_type not in CONTENT_TYPES:
        return ""

    lines = [
        "\n\n--- CURRENT SCREEN CONTEXT (live, auto-updated) ---",
        f"Current screen: {ctx.last_summary}",
    ]

    type_hints = {
        "code":     "Candidate is sharing code. Reference specific things you can see and ask about their implementation.",
        "document": "Candidate is sharing a document. Reference visible content and ask targeted questions.",
        "slide":    "Candidate is sharing a presentation slide. Ask them to walk through it or elaborate on key points.",
        "browser":  "Candidate is sharing their browser. Reference what you see and weave it into the interview.",
    }
    hint = type_hints.get(ctx.screen_type)
    if hint:
        lines.append(hint)

    if ctx.raw_text_excerpt:
        lines.append(f'Key visible text: "{ctx.raw_text_excerpt[:200]}"')

    if ctx.key_entities:
        lines.append(f"Notable items visible: {', '.join(ctx.key_entities[:5])}")

    lines.append("--- END SCREEN CONTEXT ---")
    return "\n".join(lines)
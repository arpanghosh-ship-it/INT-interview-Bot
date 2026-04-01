# #!/usr/bin/env python3
# """
# vision_worker.py — Async per-session vision worker.

# Pipeline:
#     Playwright page
#       → capture_frame()            every CAPTURE_INTERVAL seconds
#       → frames_are_different()     perceptual hash diff detection
#       → _analyze_frame_sync()      vision model call (OpenAI, runs in thread pool)
#       → screen_context store       updates last_summary, screen_type, etc.
#       → realtime.py                reads context and injects into session.update

# Runs as a third asyncio task in main.py alongside:
#     - run_meet()       (Playwright + Chrome)
#     - run_realtime()   (GPT Realtime WebSocket + STT + TTS)

# CRITICAL: vision analysis runs in run_in_executor (thread pool) so it NEVER
# blocks the asyncio event loop. The voice pipeline is completely unaffected.

# All configuration is via .env:
#     VISION_MODEL              — OpenAI model to use (default: gpt-4o-mini)
#     VISION_CAPTURE_INTERVAL   — Seconds between captures (default: 2.0)
#     VISION_DIFF_THRESHOLD     — Min diff score to trigger analysis (default: 0.08)
#     VISION_MAX_PER_MINUTE     — Max vision API calls per minute (default: 10)
# """

# import asyncio
# import base64
# import json
# import os
# import time
# from typing import Optional

# from vision_capture import capture_frame
# from vision_diff import frames_are_different
# import screen_context as ctx_store


# # ── Configuration ─────────────────────────────────────────────────────────────

# CAPTURE_INTERVAL        = float(os.getenv("VISION_CAPTURE_INTERVAL",  "2.0"))
# DIFF_THRESHOLD          = float(os.getenv("VISION_DIFF_THRESHOLD",    "0.08"))
# MAX_ANALYSES_PER_MINUTE = int(os.getenv("VISION_MAX_PER_MINUTE",      "10"))
# VISION_MODEL            = os.getenv("VISION_MODEL", "gpt-4o-mini")


# # ── Vision model system prompt ────────────────────────────────────────────────

# _VISION_SYSTEM_PROMPT = """You are a screen analysis assistant embedded inside an AI voice interviewer bot running on Google Meet.

# During a live interview, you receive screenshots from the bot's Chrome window.
# The candidate may be sharing their screen to show code, a document, a presentation, or a browser.

# Your job: analyze what is CURRENTLY visible and return a SHORT structured JSON summary.

# Focus on:
#   - Shared screens showing code editors, IDEs, terminals
#   - Documents, PDFs, README files
#   - Presentation slides
#   - Whiteboard or drawing tools
#   - Browser content (GitHub, StackOverflow, etc.)

# Ignore:
#   - Standard Google Meet UI (grid of video tiles, toolbar)
#   - The bot's own video feed
#   - Generic desktop backgrounds with nothing relevant

# Respond with ONLY this exact JSON structure (no markdown fences, no explanation):
# {
#   "summary": "1-2 sentence plain English description of what is currently visible",
#   "screen_type": "code | document | slide | browser | video | empty | unknown",
#   "key_entities": ["up to 5 specific items visible, e.g. function names, slide titles"],
#   "raw_text_excerpt": "up to 150 chars of the most important text visible on screen, or empty string if none",
#   "confidence": 0.85
# }

# Confidence guide:
#   0.9+  → clearly a shared screen with meaningful content
#   0.6   → possibly shared content, some uncertainty
#   0.3   → just the Meet UI / video grid / nothing shared
#   0.1   → completely unclear

# Keep summary under 2 sentences. This output feeds directly into a voice interview AI that will reference it live."""


# # ── Vision analysis (sync — runs in thread pool) ──────────────────────────────

# def _analyze_frame_sync(
#     image_bytes: bytes,
#     openai_api_key: str,
#     session_id: str,
# ) -> Optional[dict]:
#     """
#     Sends the screenshot to the vision model and returns parsed JSON.

#     This is a synchronous function intentionally — called via run_in_executor
#     so it never blocks the asyncio event loop.

#     Returns parsed dict on success, None on any failure.
#     """
#     from openai import OpenAI

#     sid8 = session_id.replace("-", "")[:8] if session_id else "--------"

#     try:
#         client = OpenAI(api_key=openai_api_key)
#         b64 = base64.b64encode(image_bytes).decode("utf-8")

#         response = client.chat.completions.create(
#             model=VISION_MODEL,
#             messages=[
#                 {"role": "system", "content": _VISION_SYSTEM_PROMPT},
#                 {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "image_url",
#                             "image_url": {
#                                 # "low" detail = ~512x512 internal resolution
#                                 # Cheaper, faster, and sufficient for screen content analysis
#                                 "url": f"data:image/png;base64,{b64}",
#                                 "detail": "low",
#                             },
#                         },
#                         {
#                             "type": "text",
#                             "text": "Analyze this screenshot. Return only the JSON.",
#                         },
#                     ],
#                 },
#             ],
#             max_tokens=250,
#             temperature=0.1,    # Low temperature = consistent structured output
#         )

#         raw = response.choices[0].message.content.strip()

#         # Strip markdown fences if the model wraps output in ```json ... ```
#         if raw.startswith("```"):
#             parts = raw.split("```")
#             raw = parts[1] if len(parts) > 1 else raw
#             if raw.startswith("json"):
#                 raw = raw[4:]
#         raw = raw.strip()

#         data = json.loads(raw)

#         screen_type = data.get("screen_type", "?")
#         confidence  = float(data.get("confidence", 0.0))
#         summary     = data.get("summary", "")

#         print(
#             f"[VISION] 👁  [{sid8}] {screen_type} (conf={confidence:.1f}): {summary[:80]}",
#             flush=True,
#         )
#         return data

#     except json.JSONDecodeError as e:
#         print(f"[VISION] ⚠️  [{sid8}] JSON parse error: {e} | raw: {raw[:100] if 'raw' in dir() else '?'}", flush=True)
#         return None
#     except Exception as e:
#         print(f"[VISION] ⚠️  [{sid8}] Analysis failed ({type(e).__name__}): {e}", flush=True)
#         return None


# # ── VisionWorker ──────────────────────────────────────────────────────────────

# class VisionWorker:
#     """
#     Per-session async vision worker.

#     One instance per session, started by main.py after the bot joins the meeting.
#     Stopped via stop_event (asyncio.Event) when the session ends.
#     """

#     def __init__(self, session_id: str, openai_api_key: str):
#         self.session_id = session_id
#         self.sid8       = session_id.replace("-", "")[:8]
#         self.openai_api_key = openai_api_key

#         self._prev_frame: Optional[bytes] = None
#         self._analysis_times: list[float] = []

#     # ── Rate limit ─────────────────────────────────────────────────────────────

#     def _is_rate_limited(self) -> bool:
#         """
#         Returns True if we've hit the per-minute analysis cap.
#         Cleans up the timestamp list as a side-effect.
#         """
#         now = time.time()
#         self._analysis_times = [t for t in self._analysis_times if now - t < 60.0]
#         return len(self._analysis_times) >= MAX_ANALYSES_PER_MINUTE

#     # ── Main loop ──────────────────────────────────────────────────────────────

#     async def run(self, page, stop_event: asyncio.Event):
#         """
#         Main worker loop.

#         Args:
#             page:       Playwright page object from join_meet.py (via page_holder).
#             stop_event: Set by main.py when the session ends — triggers clean shutdown.
#         """
#         ctx_store.get_or_create(self.session_id)

#         print(
#             f"[VISION] 🚀 [{self.sid8}] Worker started. "
#             f"model={VISION_MODEL} | interval={CAPTURE_INTERVAL}s | "
#             f"max={MAX_ANALYSES_PER_MINUTE}/min | diff_thresh={DIFF_THRESHOLD}",
#             flush=True,
#         )

#         while not stop_event.is_set():
#             try:
#                 await self._tick(page)
#             except asyncio.CancelledError:
#                 break
#             except Exception as e:
#                 print(f"[VISION] ⚠️  [{self.sid8}] Tick error: {e}", flush=True)

#             # Sleep for CAPTURE_INTERVAL, but wake up early if stop_event fires
#             try:
#                 await asyncio.wait_for(stop_event.wait(), timeout=CAPTURE_INTERVAL)
#                 break   # stop_event was set — clean exit
#             except asyncio.TimeoutError:
#                 pass    # Normal: interval elapsed, continue loop

#         # Cleanup
#         ctx_store.remove(self.session_id)
#         print(f"[VISION] 🛑 [{self.sid8}] Worker stopped. Total analyses: {len(self._analysis_times)}", flush=True)

#     # ── Single tick ────────────────────────────────────────────────────────────

#     async def _tick(self, page):
#         """One capture → diff → analyze → store cycle."""

#         # 1. Capture current viewport
#         frame = await capture_frame(page)
#         if not frame:
#             return

#         # 2. Diff detection: compare with previous frame
#         if self._prev_frame is not None:
#             changed, diff_score = frames_are_different(self._prev_frame, frame)
#         else:
#             changed, diff_score = True, 1.0    # First frame: always analyze

#         if not changed:
#             return  # Screen unchanged — no analysis needed

#         self._prev_frame = frame

#         # 3. Rate limit guard
#         if self._is_rate_limited():
#             print(
#                 f"[VISION] ⏸  [{self.sid8}] Rate cap ({MAX_ANALYSES_PER_MINUTE}/min) — skipping",
#                 flush=True,
#             )
#             return

#         # 4. Run analysis in thread pool — NEVER blocks the event loop
#         print(
#             f"[VISION] 📸 [{self.sid8}] Screen changed (diff={diff_score:.3f}) → analyzing...",
#             flush=True,
#         )

#         loop = asyncio.get_event_loop()
#         data = await loop.run_in_executor(
#             None,                     # Default thread pool
#             _analyze_frame_sync,
#             frame,
#             self.openai_api_key,
#             self.session_id,
#         )

#         if not data:
#             return

#         # 5. Update per-session context store
#         self._analysis_times.append(time.time())

#         existing_ctx = ctx_store.get_context(self.session_id)
#         new_count = (existing_ctx.analysis_count + 1) if existing_ctx else 1

#         ctx_store.update(
#             self.session_id,
#             last_summary        = data.get("summary", ""),
#             last_seen_at        = time.time(),
#             screen_type         = data.get("screen_type", "unknown"),
#             key_entities        = data.get("key_entities", []),
#             raw_text_excerpt    = data.get("raw_text_excerpt", ""),
#             confidence          = float(data.get("confidence", 0.0)),
#             changed_recently    = True,   # Signals realtime.py to send session.update
#             analysis_count      = new_count,
#         )












































#!/usr/bin/env python3
"""
vision_worker.py — Async per-session vision worker (v2).

Pipeline:
    Playwright page
      → capture_frame()               every CAPTURE_INTERVAL seconds
      → frames_are_different()        perceptual hash diff detection
      → _analyze_frame_sync()         vision model call (runs in thread pool)
      → is_significant_change()       decides Tier 1 vs Tier 2 injection
      → screen_context store          update + mark live event if significant
      → realtime.py                   picks up live event or background context

Runs as a third asyncio task in main.py alongside:
    - run_meet()       (Playwright + Chrome)
    - run_realtime()   (GPT Realtime WebSocket + STT + TTS)

CRITICAL: vision analysis runs in run_in_executor (thread pool) — NEVER blocks
the asyncio event loop. Voice pipeline latency is completely unaffected.

v2 changes vs v1:
  - CAPTURE_INTERVAL default: 1.0s (was 2.0s) — faster screen detection
  - DIFF_THRESHOLD default: 0.05 (was 0.08)  — more sensitive to changes
  - MAX_PER_MINUTE default: 15 (was 10)       — higher analysis budget
  - image detail: "auto" (was "low")          — better for code and text
  - Calls is_significant_change() after each analysis
  - Calls mark_as_live_event() + build_live_event_text() for significant changes
  - Always analyzes the first frame (no diff check on frame 0)

All tunable via .env:
    VISION_MODEL              — OpenAI model (default: gpt-4o-mini)
    VISION_CAPTURE_INTERVAL   — Seconds between captures (default: 1.0)
    VISION_DIFF_THRESHOLD     — Min diff to trigger analysis (default: 0.05)
    VISION_MAX_PER_MINUTE     — Max vision API calls per minute (default: 15)
"""

import asyncio
import base64
import json
import os
import time
from typing import Optional

from vision_capture import capture_frame
from vision_diff import frames_are_different
import screen_context as ctx_store


# ── Configuration ─────────────────────────────────────────────────────────────

CAPTURE_INTERVAL        = float(os.getenv("VISION_CAPTURE_INTERVAL",  "1.0"))
DIFF_THRESHOLD          = float(os.getenv("VISION_DIFF_THRESHOLD",    "0.05"))
MAX_ANALYSES_PER_MINUTE = int(os.getenv("VISION_MAX_PER_MINUTE",      "15"))
VISION_MODEL            = os.getenv("VISION_MODEL", "gpt-4o-mini")


# ── Vision model system prompt ────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """You are a screen analysis assistant embedded inside an AI voice interviewer bot running on Google Meet.

During a live interview, you receive screenshots from the bot's Chrome window.
The candidate may share their screen to show code, a document, a presentation, slides, or a browser.

Your job: analyze what is CURRENTLY visible and return a SHORT structured JSON summary.

Focus on:
  - Code editors, IDEs, terminals, command line output
  - Documents, PDFs, README files, text files
  - Presentation slides, diagrams, whiteboards
  - Browser content: GitHub, StackOverflow, documentation, web apps
  - Any other shared content the candidate is deliberately showing

Ignore:
  - Standard Google Meet UI (video grid, toolbar, participant panel, chat)
  - The bot's own video tile
  - Empty or near-empty screens with just desktop background

Respond with ONLY this exact JSON (no markdown fences, no explanation, no preamble):
{
  "summary": "1-2 sentence plain English description of what is currently visible",
  "screen_type": "code | document | slide | browser | video | empty | unknown",
  "key_entities": ["up to 5 specific items: function names, slide titles, file names, URLs"],
  "raw_text_excerpt": "up to 150 chars of the most important visible text, or empty string",
  "confidence": 0.85
}

screen_type guide:
  code      → IDE, editor, terminal, code file, notebook (.py, .js, .ipynb, etc.)
  document  → PDF, Word doc, README, text file, notes
  slide     → Presentation, PowerPoint, Google Slides, Keynote, diagram
  browser   → Web browser with a website, GitHub page, docs, web app
  video     → Video player, YouTube, screen recording being played
  empty     → Just the Meet interface / video grid, nothing meaningful shared
  unknown   → Something is visible but unclear what

confidence guide:
  0.9+  → clearly meaningful shared content
  0.7   → likely shared content, minor uncertainty
  0.4   → some content visible but uncertain
  0.1   → just the Meet UI or nothing meaningful

Keep summary under 2 sentences and specific. This output goes directly into a live voice interview."""


# ── Vision analysis (sync — runs in thread pool) ──────────────────────────────

def _analyze_frame_sync(
    image_bytes: bytes,
    openai_api_key: str,
    session_id: str,
) -> Optional[dict]:
    """
    Sends the screenshot to the vision model and returns parsed JSON.
    Synchronous by design — called via run_in_executor so it never blocks the event loop.
    Returns parsed dict on success, None on any failure.
    """
    from openai import OpenAI

    sid8 = session_id.replace("-", "")[:8] if session_id else "--------"
    raw = ""

    try:
        client = OpenAI(api_key=openai_api_key)
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                # "auto" lets GPT decide resolution based on content.
                                # Better for code/text than "low" (which was 512px).
                                # Slightly more tokens but dramatically better text accuracy.
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "auto",
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this screenshot. Return only the JSON.",
                        },
                    ],
                },
            ],
            max_tokens=300,
            temperature=0.1,    # Low temperature = consistent structured output
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if the model wraps output in ```json ... ```
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        screen_type = data.get("screen_type", "unknown")
        confidence  = float(data.get("confidence", 0.0))
        summary     = data.get("summary", "")

        print(
            f"[VISION] 👁  [{sid8}] {screen_type} (conf={confidence:.1f}): {summary[:80]}",
            flush=True,
        )
        return data

    except json.JSONDecodeError as e:
        print(f"[VISION] ⚠️  [{sid8}] JSON parse error: {e} | raw: {raw[:100]}", flush=True)
        return None
    except Exception as e:
        print(f"[VISION] ⚠️  [{sid8}] Analysis failed ({type(e).__name__}): {e}", flush=True)
        return None


# ── VisionWorker ──────────────────────────────────────────────────────────────

class VisionWorker:
    """
    Per-session async vision worker. One instance per session.
    Started by main.py after the bot joins the meeting.
    Stopped via stop_event when the session ends.
    """

    def __init__(self, session_id: str, openai_api_key: str):
        self.session_id      = session_id
        self.sid8            = session_id.replace("-", "")[:8]
        self.openai_api_key  = openai_api_key

        self._prev_frame: Optional[bytes] = None
        self._analysis_times: list[float] = []
        self._frame_count: int = 0          # Total frames captured (for first-frame logic)

    # ── Rate limit ─────────────────────────────────────────────────────────────

    def _is_rate_limited(self) -> bool:
        now = time.time()
        self._analysis_times = [t for t in self._analysis_times if now - t < 60.0]
        return len(self._analysis_times) >= MAX_ANALYSES_PER_MINUTE

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def run(self, page, stop_event: asyncio.Event):
        """
        Main worker loop.

        Args:
            page:       Playwright page object from join_meet.py (via page_holder).
            stop_event: Set by main.py when the session ends — triggers clean shutdown.
        """
        ctx_store.get_or_create(self.session_id)

        print(
            f"[VISION] 🚀 [{self.sid8}] Worker started. "
            f"model={VISION_MODEL} | interval={CAPTURE_INTERVAL}s | "
            f"max={MAX_ANALYSES_PER_MINUTE}/min | diff_thresh={DIFF_THRESHOLD}",
            flush=True,
        )

        while not stop_event.is_set():
            try:
                await self._tick(page)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[VISION] ⚠️  [{self.sid8}] Tick error: {e}", flush=True)

            # Sleep for CAPTURE_INTERVAL, exit early if stop_event fires
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=CAPTURE_INTERVAL)
                break   # stop_event fired — clean exit
            except asyncio.TimeoutError:
                pass    # Normal: interval elapsed, keep going

        ctx_store.remove(self.session_id)
        print(
            f"[VISION] 🛑 [{self.sid8}] Worker stopped. "
            f"Total frames: {self._frame_count}, analyses: {len(self._analysis_times)}",
            flush=True,
        )

    # ── Single tick ────────────────────────────────────────────────────────────

    async def _tick(self, page):
        """One capture → diff → analyze → context update cycle."""

        # 1. Capture current viewport
        frame = await capture_frame(page)
        if not frame:
            return

        self._frame_count += 1

        # 2. Diff detection
        # Frame 0 is always analyzed regardless of diff — gives us the initial state.
        if self._frame_count == 1:
            changed, diff_score = True, 1.0
        else:
            changed, diff_score = frames_are_different(self._prev_frame, frame)

        if not changed:
            return  # Screen unchanged — skip analysis

        self._prev_frame = frame

        # 3. Rate limit guard
        if self._is_rate_limited():
            print(
                f"[VISION] ⏸  [{self.sid8}] Rate cap ({MAX_ANALYSES_PER_MINUTE}/min) — skipping",
                flush=True,
            )
            return

        # 4. Run analysis in thread pool — never blocks the event loop
        print(
            f"[VISION] 📸 [{self.sid8}] Screen changed (diff={diff_score:.3f}) → analyzing...",
            flush=True,
        )

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            _analyze_frame_sync,
            frame,
            self.openai_api_key,
            self.session_id,
        )

        if not data:
            return

        new_type       = data.get("screen_type", "unknown")
        new_confidence = float(data.get("confidence", 0.0))
        new_summary    = data.get("summary", "")
        new_entities   = data.get("key_entities", [])
        new_excerpt    = data.get("raw_text_excerpt", "")

        # 5. Check for significant change BEFORE updating context
        #    (ctx still holds the OLD state at this point)
        current_ctx = ctx_store.get_context(self.session_id)
        significant, reason = ctx_store.is_significant_change(
            current_ctx, new_type, new_confidence
        ) if current_ctx else (False, "")

        # 6. Update per-session context store
        self._analysis_times.append(time.time())
        existing_count = current_ctx.analysis_count if current_ctx else 0

        ctx_store.update(
            self.session_id,
            last_summary        = new_summary,
            last_seen_at        = time.time(),
            screen_type         = new_type,
            key_entities        = new_entities,
            raw_text_excerpt    = new_excerpt,
            confidence          = new_confidence,
            changed_recently    = True,          # Tier 2: signal session.update
            analysis_count      = existing_count + 1,
        )

        # 7. Tier 1: If significant change — build and store live event text
        if significant and reason:
            event_text = ctx_store.build_live_event_text(
                summary          = new_summary,
                screen_type      = new_type,
                key_entities     = new_entities,
                raw_text_excerpt = new_excerpt,
                reason           = reason,
            )
            ctx_store.mark_as_live_event(self.session_id, event_text)
            print(
                f"[VISION] 🔔 [{self.sid8}] Significant change ({reason}) → live event queued",
                flush=True,
            )
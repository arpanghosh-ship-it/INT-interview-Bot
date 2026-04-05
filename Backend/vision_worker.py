#!/usr/bin/env python3
"""
vision_worker.py — Per-session screen capture, diff, and analysis (v6)

KEY CHANGES IN v6:
─────────────────────────────────────────────────────────────────────
1. capture_event CLEARED after on-demand capture completes.
   realtime.py watches for capture_event to clear as its signal that
   vision is done. Without this, the wait loop in realtime.py just
   spins until timeout every single time.

2. raw_text_excerpt increased from 200 → 500 chars.
   200 chars was not enough to capture actual bullet points from a resume.
   With the previous limit, the bot only got a generic summary and then
   hallucinated plausible-sounding content. 500 chars captures 3-4 full
   bullet points verbatim.

3. Vision prompt restructured:
   - Explicitly instructs the model to extract VERBATIM bullet points
   - Adds "bullet_points" field to JSON output for resume/document content
   - Increased max_tokens: 400 → 700 to accommodate longer text extraction
   - key_entities increased from 5 → 8 items

4. Smart state machine (IDLE/SHARING) preserved from v5.
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

CAPTURE_INTERVAL        = float(os.getenv("VISION_CAPTURE_INTERVAL", "1.0"))
DIFF_THRESHOLD          = float(os.getenv("VISION_DIFF_THRESHOLD",   "0.05"))
MAX_ANALYSES_PER_MINUTE = int(os.getenv("VISION_MAX_PER_MINUTE",     "10"))

IDLE_CHECK_INTERVAL    = 2.0
SHARE_START_DIFF       = 0.20
CONSECUTIVE_EMPTY_STOP = 2
CONSECUTIVE_FAIL_CLEAR = 3


# ── Vision analysis prompt ────────────────────────────────────────────────────

_VISION_PROMPT = """You are a screen analysis assistant for an AI voice interviewer bot on Google Meet.

The candidate may be sharing their screen. Your primary job is to ACCURATELY READ and EXTRACT
the actual text content visible on screen — especially from resumes and documents.

CRITICAL RULE: Extract text VERBATIM as it appears on screen. Do NOT paraphrase, summarize,
or invent content. If you can read "Built an Aadhaar Masking system using YOLOv8" then write
exactly that — word for word. Never replace actual text with generic descriptions.

Return ONLY this exact JSON (no markdown, no explanation):
{
  "summary": "1-2 sentence description of what is visible",
  "screen_type": "code | document | slide | browser | video | empty | unknown",
  "key_entities": ["up to 8 items: company names, skill names, section headers, tool names, dates"],
  "raw_text_excerpt": "up to 500 chars of the most important visible text, copied VERBATIM from the screen — especially bullet points, job titles, company names, dates, and skills sections",
  "bullet_points": ["list every bullet point visible on screen, verbatim, up to 10 items — empty list if no bullets visible"],
  "confidence": 0.9
}

For resumes/documents: Extract the actual text from bullet points, not summaries.
For code: Include actual function/variable names, not descriptions.
For slides: Include actual title text and bullet text.

screen_type:
  document → resume, PDF, Word doc, README
  code → IDE, editor, terminal, notebook
  slide → Presentation, Google Slides, diagram
  browser → Web browser
  video → Video player
  empty → Just the Google Meet UI, no shared content
  unknown → Unclear

empty = confidence 0.1, real content = confidence 0.9+"""


# ── OpenAI vision analysis ────────────────────────────────────────────────────

def _analyze_frame_sync(
    image_bytes: bytes,
    openai_api_key: str,
    session_id: str,
    on_demand: bool = False,
) -> Optional[dict]:
    from openai import OpenAI

    sid8 = session_id.replace("-", "")[:8] if session_id else "--------"
    raw = ""

    try:
        client = OpenAI(api_key=openai_api_key)
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _VISION_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Analyze this screenshot. "
                                "Extract all visible text VERBATIM, especially bullet points. "
                                "Return only the JSON."
                            ),
                        },
                    ],
                },
            ],
            max_tokens=700,     # increased from 400 to capture more text
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
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
        tag = "📷 ON-DEMAND" if on_demand else "👁 "
        print(
            f"[VISION] {tag} [{sid8}] {screen_type} (conf={confidence:.1f}): {summary[:80]}",
            flush=True,
        )

        # Log bullet points if extracted
        bullets = data.get("bullet_points", [])
        if bullets and on_demand:
            print(f"[VISION] 📋 [{sid8}] Bullets extracted: {len(bullets)}", flush=True)
            for i, b in enumerate(bullets[:3]):
                print(f"[VISION]   [{i+1}] {b[:100]}", flush=True)

        return data

    except json.JSONDecodeError as e:
        print(f"[VISION] ⚠️  [{sid8}] JSON error: {e} | raw: {raw[:100]}", flush=True)
        return None
    except Exception as e:
        print(f"[VISION] ⚠️  [{sid8}] Analysis failed ({type(e).__name__}): {e}", flush=True)
        return None


# ── VisionWorker ──────────────────────────────────────────────────────────────

class VisionWorker:
    def __init__(self, session_id: str, openai_api_key: str):
        self.session_id     = session_id
        self.sid8           = session_id.replace("-", "")[:8]
        self.openai_api_key = openai_api_key

        self._prev_frame: Optional[bytes] = None
        self._analysis_times: list[float] = []
        self._frame_count: int = 0

        self._is_sharing: bool = False
        self._consecutive_empty: int = 0
        self._consecutive_failures: int = 0

    def _is_rate_limited(self) -> bool:
        now = time.time()
        self._analysis_times = [t for t in self._analysis_times if now - t < 60.0]
        return len(self._analysis_times) >= MAX_ANALYSES_PER_MINUTE

    def _invalidate_stale_context(self):
        ctx = ctx_store.get_context(self.session_id)
        if ctx and ctx.last_summary:
            ctx_store.update(
                self.session_id,
                last_summary="", screen_type="unknown", confidence=0.0,
                changed_recently=True, key_entities=[], raw_text_excerpt="",
            )
            print(
                f"[VISION] ⚠️  [{self.sid8}] Stale context cleared after "
                f"{self._consecutive_failures} failures.",
                flush=True,
            )

    async def run(
        self,
        page,
        stop_event: asyncio.Event,
        capture_event: asyncio.Event = None,
    ):
        ctx_store.get_or_create(self.session_id)

        print(
            f"[VISION] 🚀 [{self.sid8}] Worker started. "
            f"model=gpt-4o-mini (detail=high, max_tokens=700) | "
            f"capture={CAPTURE_INTERVAL}s | idle_check={IDLE_CHECK_INTERVAL}s | "
            f"max={MAX_ANALYSES_PER_MINUTE}/min | "
            f"on_demand={'✅' if capture_event else '❌'}",
            flush=True,
        )

        while not stop_event.is_set():
            try:
                if capture_event is not None and capture_event.is_set():
                    await self._tick_on_demand(page)
                    # ── CRITICAL: clear the event AFTER capture completes ──────
                    # realtime.py is waiting on this event to clear before sending
                    # response.create. Clearing it here signals "vision is done,
                    # safe to generate response now."
                    capture_event.clear()
                    print(f"[VISION] ✅ [{self.sid8}] On-demand complete — capture_event cleared", flush=True)

                elif self._is_sharing:
                    await self._tick_sharing(page)
                else:
                    await self._tick_idle(page)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[VISION] ⚠️  [{self.sid8}] Tick error: {e}", flush=True)
                # If on-demand failed, clear the event so realtime doesn't wait forever
                if capture_event is not None and capture_event.is_set():
                    capture_event.clear()

            sleep_interval = CAPTURE_INTERVAL if self._is_sharing else IDLE_CHECK_INTERVAL
            try:
                if capture_event is not None:
                    done, pending = await asyncio.wait(
                        [
                            asyncio.ensure_future(stop_event.wait()),
                            asyncio.ensure_future(capture_event.wait()),
                        ],
                        timeout=sleep_interval,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    if stop_event.is_set():
                        break
                else:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_interval)
                    break
            except asyncio.TimeoutError:
                pass

        ctx_store.remove(self.session_id)
        print(
            f"[VISION] 🛑 [{self.sid8}] Worker stopped. "
            f"Frames: {self._frame_count} | Analyses: {len(self._analysis_times)}",
            flush=True,
        )

    async def _tick_on_demand(self, page):
        """
        Triggered by realtime.py when the candidate stops speaking.
        Immediately captures and analyzes the current screen.
        Clears capture_event when done so realtime.py can proceed.
        """
        frame = await capture_frame(page)
        if not frame:
            return

        self._prev_frame = frame
        self._frame_count += 1

        if self._is_rate_limited():
            print(f"[VISION] ⏸  [{self.sid8}] On-demand skipped (rate limited)", flush=True)
            return

        print(f"[VISION] 📷 [{self.sid8}] On-demand capture (speech_stopped)...", flush=True)

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, _analyze_frame_sync, frame, self.openai_api_key, self.session_id, True
        )

        if data is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= CONSECUTIVE_FAIL_CLEAR:
                self._invalidate_stale_context()
            return

        self._consecutive_failures = 0
        self._analysis_times.append(time.time())

        screen_type = data.get("screen_type", "unknown")
        confidence  = float(data.get("confidence", 0.0))

        if screen_type not in ("empty", "unknown") and confidence >= 0.7:
            if not self._is_sharing:
                self._is_sharing = True
                self._consecutive_empty = 0
                print(f"[VISION] 📺 [{self.sid8}] On-demand: sharing STARTED", flush=True)
            self._store_result(data, significant_override=True)
        elif screen_type in ("empty", "unknown") and confidence < 0.4:
            if self._is_sharing:
                self._is_sharing = False
                print(f"[VISION] 📴 [{self.sid8}] On-demand: sharing STOPPED", flush=True)
                ctx_store.update(
                    self.session_id,
                    last_summary="", screen_type="unknown", confidence=0.0,
                    changed_recently=True, key_entities=[], raw_text_excerpt="",
                )
        else:
            self._store_result(data)

    async def _tick_idle(self, page):
        frame = await capture_frame(page)
        if not frame:
            return

        self._frame_count += 1

        if self._prev_frame is None:
            self._prev_frame = frame
            return

        changed, diff_score = frames_are_different(self._prev_frame, frame)
        self._prev_frame = frame

        if diff_score >= SHARE_START_DIFF:
            print(
                f"[VISION] 🔍 [{self.sid8}] Large diff in IDLE (diff={diff_score:.3f}) "
                f"→ checking if sharing started...",
                flush=True,
            )
            await self._check_sharing_started(frame)

    async def _check_sharing_started(self, frame: bytes):
        if self._is_rate_limited():
            return

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, _analyze_frame_sync, frame, self.openai_api_key, self.session_id, False
        )

        if data is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= CONSECUTIVE_FAIL_CLEAR:
                self._invalidate_stale_context()
            return

        self._consecutive_failures = 0
        self._analysis_times.append(time.time())

        screen_type = data.get("screen_type", "unknown")
        confidence  = float(data.get("confidence", 0.0))

        if screen_type not in ("empty", "unknown") and confidence >= 0.7:
            self._is_sharing = True
            self._consecutive_empty = 0
            print(
                f"[VISION] 📺 [{self.sid8}] Sharing STARTED "
                f"({screen_type}, conf={confidence:.1f}) → SHARING mode",
                flush=True,
            )
            self._store_result(data)

    async def _tick_sharing(self, page):
        frame = await capture_frame(page)
        if not frame:
            return

        self._frame_count += 1

        if self._prev_frame is None:
            self._prev_frame = frame

        changed, diff_score = frames_are_different(self._prev_frame, frame)
        self._prev_frame = frame

        if not changed:
            return

        if self._is_rate_limited():
            print(f"[VISION] ⏸  [{self.sid8}] Rate cap ({MAX_ANALYSES_PER_MINUTE}/min)", flush=True)
            return

        print(f"[VISION] 📸 [{self.sid8}] Screen changed (diff={diff_score:.3f}) → analyzing...", flush=True)

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, _analyze_frame_sync, frame, self.openai_api_key, self.session_id, False
        )

        if data is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= CONSECUTIVE_FAIL_CLEAR:
                self._invalidate_stale_context()
                self._is_sharing = False
                print(f"[VISION] 🔴 [{self.sid8}] Vision unavailable → IDLE mode", flush=True)
            return

        self._consecutive_failures = 0
        self._analysis_times.append(time.time())

        screen_type = data.get("screen_type", "unknown")
        confidence  = float(data.get("confidence", 0.0))

        if screen_type in ("empty", "unknown") and confidence < 0.4:
            self._consecutive_empty += 1
            if self._consecutive_empty >= CONSECUTIVE_EMPTY_STOP:
                self._is_sharing = False
                self._consecutive_empty = 0
                print(f"[VISION] 📴 [{self.sid8}] Sharing STOPPED → IDLE mode", flush=True)
                ctx_store.update(
                    self.session_id,
                    last_summary="", screen_type="unknown", confidence=0.0,
                    changed_recently=True, key_entities=[], raw_text_excerpt="",
                )
        else:
            self._consecutive_empty = 0
            self._store_result(data)

    def _store_result(self, data: dict, significant_override: bool = False):
        new_type       = data.get("screen_type", "unknown")
        new_confidence = float(data.get("confidence", 0.0))
        new_summary    = data.get("summary", "")
        new_entities   = data.get("key_entities", [])
        new_excerpt    = data.get("raw_text_excerpt", "")

        # Merge bullet points into raw_text_excerpt for context injection
        # This gives the bot verbatim bullet text even if raw_text_excerpt is short
        bullets = data.get("bullet_points", [])
        if bullets:
            bullet_text = " | ".join(bullets[:8])
            if bullet_text and bullet_text not in new_excerpt:
                # Prepend bullets to excerpt (most important content)
                new_excerpt = bullet_text[:500]

        current_ctx = ctx_store.get_context(self.session_id)
        significant, reason = ctx_store.is_significant_change(
            current_ctx, new_type, new_confidence
        ) if current_ctx else (False, "")

        if significant_override and not significant:
            significant = True
            reason = "on_demand_refresh"

        existing_count = current_ctx.analysis_count if current_ctx else 0

        ctx_store.update(
            self.session_id,
            last_summary     = new_summary,
            last_seen_at     = time.time(),
            screen_type      = new_type,
            key_entities     = new_entities,
            raw_text_excerpt = new_excerpt,
            confidence       = new_confidence,
            changed_recently = True,
            analysis_count   = existing_count + 1,
        )

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
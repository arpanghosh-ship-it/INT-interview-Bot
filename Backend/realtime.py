#!/usr/bin/env python3
"""
realtime.py — GPT Realtime API (STT + LLM combined) — v6

LATENCY FIX: Smart vision wait — only delays when screen share is active
─────────────────────────────────────────────────────────────────────
Problem in v5:
  Every single turn waited the full VISION_WAIT_MAX_MS (1200ms) before
  firing response.create — even for turns with no screen sharing.
  "Bye", "Hello", short answers all hit the full 1200ms timeout.
  This doubled the response latency compared to the old create_response=True.

Root cause:
  The vision API call takes ~800-900ms (gpt-4o-mini with detail=high).
  VISION_WAIT_MAX_MS was 1200ms. Since vision never completed within
  1200ms, EVERY turn hit the timeout and waited the full 1200ms.

Fix: Two-path logic based on whether screen sharing is currently active.

PATH A — No active screen share (ctx.confidence < 0.7 or empty/unknown):
  1. Signal vision to capture (capture_event.set()) — fire and forget
  2. Fire response.create IMMEDIATELY — zero added latency
  3. Vision runs in the background for next turn's context
  Result: Same speed as old create_response=True behavior (~400ms)

PATH B — Active screen share detected (ctx.confidence >= 0.7, real content):
  1. Signal vision to capture (capture_event.set())
  2. Wait up to VISION_WAIT_MAX_MS for vision to complete
  3. Inject fresh screen context into session.update
  4. Fire response.create with guaranteed fresh context
  Result: ~1000-1200ms added per turn — acceptable for screen reading tasks

This gives us the best of both worlds:
  - Normal conversation: fast responses, no latency penalty
  - Screen sharing: guaranteed fresh context before every response
"""

import asyncio
import base64
import json
import os
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import websockets

# ── Constants ─────────────────────────────────────────────────────────────────
CAPTURE_RATE  = 44100
TARGET_RATE   = 24000
FRAME_MS      = 30
BARGE_IN_RMS  = 0.10

# Max time to wait for vision when screen share IS active
VISION_WAIT_MAX_MS = int(os.getenv("VISION_WAIT_MAX_MS", "1500"))

CONTEXT_CHECK_INTERVAL = float(os.getenv("VISION_CONTEXT_CHECK_INTERVAL", "1.0"))


def ts():
    return time.strftime("%H:%M:%S")


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate:
        return audio
    new_len = int(len(audio) * to_rate / from_rate)
    return np.interp(
        np.linspace(0, len(audio) - 1, new_len),
        np.arange(len(audio)),
        audio,
    ).astype(np.float32)


def _to_pcm16_b64(audio: np.ndarray) -> str:
    clipped = np.clip(audio, -1.0, 1.0)
    return base64.b64encode(
        (clipped * 32767).astype(np.int16).tobytes()
    ).decode()


# ── Main entry point ──────────────────────────────────────────────────────────
async def run_realtime(
    agent,
    mute_flag: threading.Event,
    openai_api_key: str,
    system_prompt: str,
    device_index: int = 0,
    silence_duration_ms: int = 500,
    voice_threshold: float = 0.05,
    session_id: str = "",
    capture_event: asyncio.Event = None,
):
    import screen_context as ctx_store

    spk_sink = (
        os.getenv("PULSE_SPK_SINK")
        or os.getenv("PULSE_SOURCE")
        or "VirtualSpeaker"
    )
    pulse_source = f"{spk_sink}.monitor"
    os.environ["PULSE_SOURCE"] = pulse_source
    print(f"[RT] 🔌 PULSE_SOURCE: {pulse_source}", flush=True)

    sid8 = session_id.replace("-", "")[:8] if session_id else "--------"

    device_info  = sd.query_devices(device_index)
    capture_rate = int(device_info.get("default_samplerate", CAPTURE_RATE))
    max_ch       = int(device_info.get("max_input_channels", 2))
    use_ch       = min(max_ch, 2)
    blocksize    = int(capture_rate * FRAME_MS / 1000)

    print(f"[RT] 🤖 Model   : gpt-4o-mini-realtime-preview (STT + LLM)", flush=True)
    print(f"[RT] 🎙️  Device  : [{device_index}] {device_info['name']} @ {capture_rate}Hz", flush=True)
    print(f"[RT] ⏱️  VAD     : semantic_vad, eagerness=medium, create_response=False", flush=True)
    print(f"[RT] 🔊 Noise   : near_field noise reduction ENABLED", flush=True)
    print(f"[RT] 🔈 Barge-in: threshold={BARGE_IN_RMS} RMS", flush=True)
    print(f"[RT] 👁  Vision  : smart wait — instant when idle, {VISION_WAIT_MAX_MS}ms when sharing", flush=True)

    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview"
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    audio_q = queue.Queue(maxsize=500)
    loop    = asyncio.get_event_loop()

    # Track whether a response is currently in progress to prevent duplicate errors
    _response_in_progress = False

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[RT] ⚠️  {status}", flush=True)

        mono = np.mean(indata, axis=1) if indata.ndim > 1 else indata.flatten()

        if mute_flag.is_set():
            rms = float(np.sqrt(np.mean(np.square(mono))))
            if rms > BARGE_IN_RMS:
                print(f"[RT] [{ts()}] ⚡ Barge-in (rms={rms:.3f}) — stopping bot", flush=True)
                if hasattr(agent, "interrupt"):
                    agent.interrupt()
            return

        try:
            audio_q.put_nowait(mono.copy())
        except queue.Full:
            pass

    async with websockets.connect(
        url,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=10,
    ) as ws:
        print(f"[RT] ✅ Connected to GPT Realtime WebSocket", flush=True)

        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "instructions": system_prompt,
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "input_audio_noise_reduction": {
                    "type": "near_field"
                },
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "medium",
                    "create_response": False,
                    "interrupt_response": True,
                },
                "temperature": 0.7,
                "max_response_output_tokens": 150,
            }
        }))

        # ── Audio sender ──────────────────────────────────────────────────────
        async def _send_audio():
            silence_chunk = None
            while True:
                try:
                    chunk = await loop.run_in_executor(
                        None, lambda: audio_q.get(timeout=0.1)
                    )
                    resampled = _resample(chunk, capture_rate, TARGET_RATE)
                    rms = float(np.sqrt(np.mean(np.square(resampled))))
                    if rms < voice_threshold:
                        if silence_chunk is None:
                            silence_chunk = np.zeros(len(resampled), dtype=np.float32)
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": _to_pcm16_b64(silence_chunk),
                        }))
                        continue
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": _to_pcm16_b64(resampled),
                    }))
                except queue.Empty:
                    await asyncio.sleep(0.01)
                except websockets.ConnectionClosed:
                    break
                except Exception as e:
                    print(f"[RT] ❌ Send error: {e}", flush=True)
                    break

        # ── Smart response trigger ────────────────────────────────────────────
        async def _trigger_response_after_vision():
            """
            Smart two-path logic:

            PATH A — No active screen share:
              Fire response.create immediately. Zero latency penalty.
              Vision capture still triggered in background for next turn.

            PATH B — Active screen share:
              Wait for vision to complete (up to VISION_WAIT_MAX_MS).
              Inject fresh context. Then fire response.create.
            """
            nonlocal _response_in_progress

            # Don't trigger if a response is already in progress
            if _response_in_progress:
                print(f"[RT] ⏭️  [{sid8}] Response already in progress — skipping", flush=True)
                return

            # Check current screen context to decide which path to take
            ctx = ctx_store.get_context(session_id)
            is_sharing = (
                ctx is not None
                and ctx.screen_type not in ("empty", "unknown")
                and ctx.confidence >= 0.7
                and (time.time() - ctx.last_seen_at) < 60  # not stale
            )

            if capture_event is not None:
                capture_event.set()

            if is_sharing:
                # ── PATH B: Wait for fresh vision before responding ────────────
                print(
                    f"[RT] 📷 [{sid8}] Share active ({ctx.screen_type}) — "
                    f"waiting up to {VISION_WAIT_MAX_MS}ms for vision...",
                    flush=True,
                )
                deadline = loop.time() + VISION_WAIT_MAX_MS / 1000.0

                if capture_event is not None:
                    while capture_event.is_set():
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            print(
                                f"[RT] ⏱️  [{sid8}] Vision timeout — proceeding with last known context",
                                flush=True,
                            )
                            break
                        await asyncio.sleep(0.03)

                # Inject fresh context into session
                fresh_ctx = ctx_store.get_context(session_id)
                if fresh_ctx and fresh_ctx.last_summary and fresh_ctx.confidence >= 0.7:
                    updated_instructions = _build_instructions_with_context(
                        system_prompt, fresh_ctx
                    )
                    try:
                        await ws.send(json.dumps({
                            "type": "session.update",
                            "session": {
                                "instructions": updated_instructions,
                                "input_audio_noise_reduction": {"type": "near_field"},
                            },
                        }))
                        ctx_store.mark_injected(session_id)
                        print(
                            f"[RT] 👁  [{sid8}] Context injected → "
                            f'"{fresh_ctx.last_summary[:60]}"',
                            flush=True,
                        )
                    except Exception as e:
                        print(f"[RT] ⚠️  Context inject error: {e}", flush=True)
            else:
                # ── PATH A: No share — respond immediately ─────────────────────
                print(f"[RT] ⚡ [{sid8}] No active share — instant response", flush=True)
                # Vision capture is already triggered (background), don't wait

            # Fire response
            try:
                _response_in_progress = True
                await ws.send(json.dumps({"type": "response.create"}))
                print(f"[RT] ▶️  [{sid8}] response.create sent", flush=True)
            except Exception as e:
                print(f"[RT] ❌ response.create failed: {e}", flush=True)
                _response_in_progress = False

        # ── Event receiver ────────────────────────────────────────────────────
        async def _receive_events():
            nonlocal _response_in_progress
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "session.created":
                    print(f"[RT] ✅ Session ready", flush=True)
                    print(f"[RT] ✅ Listening on {pulse_source}", flush=True)

                elif etype == "input_audio_buffer.speech_started":
                    print(f"[RT] [{ts()}] 🎙️  Speech started", flush=True)

                elif etype == "input_audio_buffer.speech_stopped":
                    print(f"[RT] [{ts()}] 🎙️  Speech stopped", flush=True)
                    asyncio.ensure_future(_trigger_response_after_vision())

                elif etype == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "").strip()
                    if transcript:
                        print(f"[RT] [{ts()}] 📝 Transcript: {transcript}", flush=True)

                elif etype == "response.done":
                    # Response finished — clear the in-progress flag
                    _response_in_progress = False

                elif etype == "response.text.done":
                    text = event.get("text", "").strip()
                    if text:
                        print(f"[RT] [{ts()}] 💬 Response: {text}", flush=True)
                        threading.Thread(
                            target=agent.text_to_speech,
                            args=(text,),
                            daemon=True,
                        ).start()

                elif etype == "error":
                    err = event.get("error", {})
                    msg = err.get("message", str(err))
                    # Don't spam logs for the "already in progress" race condition
                    if "already has an active response" not in msg:
                        print(f"[RT] ❌ API error: {msg}", flush=True)
                    _response_in_progress = False

        # ── Background context updater (Tier 1 live events) ───────────────────
        async def _update_context():
            while True:
                await asyncio.sleep(CONTEXT_CHECK_INTERVAL)
                try:
                    has_event, event_text = ctx_store.get_live_event(session_id)
                    if has_event and event_text:
                        await ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{
                                    "type": "input_text",
                                    "text": event_text,
                                }],
                            },
                        }))
                        ctx_store.mark_live_event_consumed(session_id)
                        print(
                            f"[RT] 🔔 [{sid8}] Tier1 live event → "
                            f'"{event_text[:60]}"',
                            flush=True,
                        )

                except websockets.ConnectionClosed:
                    break
                except Exception as e:
                    print(f"[RT] ⚠️  Context update error: {e}", flush=True)

        # ── Start audio capture stream ─────────────────────────────────────────
        with sd.InputStream(
            device=device_index,
            samplerate=capture_rate,
            channels=use_ch,
            dtype="float32",
            blocksize=blocksize,
            callback=audio_callback,
        ):
            print(f"[RT] 🎧 Audio capture started @ {capture_rate}Hz", flush=True)
            try:
                await asyncio.gather(
                    _send_audio(),
                    _receive_events(),
                    _update_context(),
                )
            except asyncio.CancelledError:
                print(f"[RT] 🛑 Realtime session cancelled.", flush=True)
                raise


def _build_instructions_with_context(base_prompt: str, ctx) -> str:
    """Append fresh screen context to system prompt before response.create."""
    import time as _time
    age = _time.time() - ctx.last_seen_at
    if age > 60:
        return base_prompt
    if ctx.screen_type in ("empty", "unknown") or ctx.confidence < 0.4:
        return base_prompt

    lines = [
        base_prompt,
        "\n\n--- CURRENT SCREEN CONTEXT (captured right now) ---",
        f"The candidate is sharing their screen.",
        f"What is visible: {ctx.last_summary}",
    ]

    type_hints = {
        "code": (
            "This is code. Reference specific things you can actually read — "
            "function names, variable names, list values, output. "
            "Ask about their logic or verify their result."
        ),
        "document": (
            "This is a document. Reference visible sections, names, dates, and "
            "bullet points you can read from the raw text below. "
            "ONLY mention content that appears explicitly in the raw text — "
            "do NOT guess or invent content not listed there."
        ),
        "slide": "This is a presentation. Ask them to walk you through it or elaborate on a specific point.",
        "browser": "This is a browser window. Reference what is actually visible.",
    }
    hint = type_hints.get(ctx.screen_type)
    if hint:
        lines.append(hint)

    if ctx.raw_text_excerpt:
        lines.append(
            f'Verbatim text visible on screen: "{ctx.raw_text_excerpt}"'
        )

    if ctx.key_entities:
        lines.append(f"Key items visible: {', '.join(ctx.key_entities[:8])}")

    lines += [
        "CRITICAL: Only reference content explicitly listed above. Do NOT invent content.",
        "If asked to read something, read verbatim from the text above.",
        "--- END SCREEN CONTEXT ---",
    ]

    return "\n".join(lines)
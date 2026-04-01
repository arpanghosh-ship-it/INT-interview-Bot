# #!/usr/bin/env python3
# """
# realtime.py — GPT Realtime API (STT + LLM combined)

# Flow:
#   VSpk_{sid}.monitor (44100Hz)          ← per-session speaker sink monitor
#   → resample to 24000Hz PCM16
#   → RMS threshold filter
#   → GPT Realtime WebSocket (STT + LLM)
#   → text response
#   → agent.text_to_speech()  (Cartesia Sonic-3)

# FIX: PULSE_SOURCE is now read from PULSE_SPK_SINK env var (set per-session
#      by api.py) instead of being hardcoded to VirtualSpeaker.monitor.

# VISION CHANGE (v2):
#   run_realtime() now accepts a `session_id` parameter.
#   A third coroutine `_update_context()` runs alongside _send_audio() and
#   _receive_events(). Every 3 seconds it checks screen_context.has_new_context().
#   If the vision worker has posted a new screen analysis, it sends a session.update
#   to the GPT Realtime WebSocket with the updated instructions (original system
#   prompt + screen context appended). This keeps the voice + screen context
#   fully aligned without blocking the audio loop.
# """

# import asyncio
# import base64
# import json
# import os
# import queue
# import threading
# import time

# import numpy as np
# import sounddevice as sd
# import websockets

# # ── Constants ─────────────────────────────────────────────────────────────────
# CAPTURE_RATE  = 44100
# TARGET_RATE   = 24000
# FRAME_MS      = 30
# BARGE_IN_RMS  = 0.04

# # How often to check for new screen context and push session.update (seconds)
# CONTEXT_CHECK_INTERVAL = float(os.getenv("VISION_CONTEXT_CHECK_INTERVAL", "3.0"))


# def ts():
#     return time.strftime("%H:%M:%S")


# def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
#     if from_rate == to_rate:
#         return audio
#     new_len = int(len(audio) * to_rate / from_rate)
#     return np.interp(
#         np.linspace(0, len(audio) - 1, new_len),
#         np.arange(len(audio)),
#         audio,
#     ).astype(np.float32)


# def _to_pcm16_b64(audio: np.ndarray) -> str:
#     clipped = np.clip(audio, -1.0, 1.0)
#     return base64.b64encode(
#         (clipped * 32767).astype(np.int16).tobytes()
#     ).decode()


# # ── Main entry point ──────────────────────────────────────────────────────────
# async def run_realtime(
#     agent,
#     mute_flag: threading.Event,
#     openai_api_key: str,
#     system_prompt: str,
#     device_index: int = 0,
#     silence_duration_ms: int = 500,
#     voice_threshold: float = 0.05,
#     session_id: str = "",               # ← VISION: needed to read screen_context store
# ):
#     # ── FIX: resolve per-session speaker sink from env ─────────────────────
#     # api.py sets PULSE_SPK_SINK = VSpk_{sid8} for each session.
#     # We need to listen on its .monitor to capture Chrome's speaker output
#     # (= candidate's voice coming from Meet).
#     # Fallback chain: PULSE_SPK_SINK → PULSE_SOURCE → global fallback
#     spk_sink = (
#         os.getenv("PULSE_SPK_SINK")         # per-session: VSpk_2fad6aeb
#         or os.getenv("PULSE_SOURCE")         # legacy fallback
#         or "VirtualSpeaker"                  # last resort
#     )
#     # The .monitor of the speaker sink is where Chrome's audio output appears
#     pulse_source = f"{spk_sink}.monitor"

#     os.environ["PULSE_SOURCE"] = pulse_source
#     print(f"[RT] 🔌 PULSE_SOURCE: {pulse_source}", flush=True)
#     # ── END FIX ────────────────────────────────────────────────────────────

#     sid8 = session_id.replace("-", "")[:8] if session_id else "--------"

#     device_info  = sd.query_devices(device_index)
#     capture_rate = int(device_info.get("default_samplerate", CAPTURE_RATE))
#     max_ch       = int(device_info.get("max_input_channels", 2))
#     use_ch       = min(max_ch, 2)
#     blocksize    = int(capture_rate * FRAME_MS / 1000)

#     print(f"[RT] 🤖 Model   : gpt-4o-mini-realtime-preview (STT + LLM)", flush=True)
#     print(f"[RT] 🎙️  Device  : [{device_index}] {device_info['name']} @ {capture_rate}Hz", flush=True)
#     print(f"[RT] ⏱️  VAD     : semantic_vad, eagerness=high", flush=True)
#     print(f"[RT] 🔈 Threshold: voice_threshold={voice_threshold} (RMS)", flush=True)
#     print(f"[RT] 👁  Vision  : context_check_interval={CONTEXT_CHECK_INTERVAL}s", flush=True)

#     url = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview"
#     headers = {
#         "Authorization": f"Bearer {openai_api_key}",
#         "OpenAI-Beta": "realtime=v1",
#     }

#     audio_q = queue.Queue(maxsize=500)
#     loop    = asyncio.get_event_loop()

#     def audio_callback(indata, frames, time_info, status):
#         if status:
#             print(f"[RT] ⚠️  {status}", flush=True)

#         mono = np.mean(indata, axis=1) if indata.ndim > 1 else indata.flatten()

#         if mute_flag.is_set():
#             rms = float(np.sqrt(np.mean(np.square(mono))))
#             if rms > BARGE_IN_RMS:
#                 print(f"[RT] [{ts()}] ⚡ Barge-in (rms={rms:.3f}) — stopping Alex", flush=True)
#                 if hasattr(agent, "interrupt"):
#                     agent.interrupt()
#             return

#         try:
#             audio_q.put_nowait(mono.copy())
#         except queue.Full:
#             pass

#     async with websockets.connect(
#         url,
#         additional_headers=headers,
#         ping_interval=20,
#         ping_timeout=10,
#     ) as ws:
#         print(f"[RT] ✅ Connected to GPT Realtime WebSocket", flush=True)

#         await ws.send(json.dumps({
#             "type": "session.update",
#             "session": {
#                 "modalities": ["text"],
#                 "instructions": system_prompt,
#                 "input_audio_format": "pcm16",
#                 "input_audio_transcription": {
#                     "model": "whisper-1"
#                 },
#                 "turn_detection": {
#                     "type": "semantic_vad",
#                     "eagerness": "high",
#                     "create_response": True,
#                     "interrupt_response": True,
#                 },
#                 "temperature": 0.8,
#                 "max_response_output_tokens": 80,
#             }
#         }))

#         # ── Audio sender ──────────────────────────────────────────────────────
#         async def _send_audio():
#             silence_chunk = None
#             while True:
#                 try:
#                     chunk = await loop.run_in_executor(
#                         None, lambda: audio_q.get(timeout=0.1)
#                     )
#                     resampled = _resample(chunk, capture_rate, TARGET_RATE)
#                     rms = float(np.sqrt(np.mean(np.square(resampled))))
#                     if rms < voice_threshold:
#                         if silence_chunk is None:
#                             silence_chunk = np.zeros(len(resampled), dtype=np.float32)
#                         await ws.send(json.dumps({
#                             "type": "input_audio_buffer.append",
#                             "audio": _to_pcm16_b64(silence_chunk),
#                         }))
#                         continue
#                     await ws.send(json.dumps({
#                         "type": "input_audio_buffer.append",
#                         "audio": _to_pcm16_b64(resampled),
#                     }))
#                 except queue.Empty:
#                     await asyncio.sleep(0.01)
#                 except websockets.ConnectionClosed:
#                     break
#                 except Exception as e:
#                     print(f"[RT] ❌ Send error: {e}", flush=True)
#                     break

#         # ── Event receiver ────────────────────────────────────────────────────
#         async def _receive_events():
#             async for raw in ws:
#                 try:
#                     event = json.loads(raw)
#                 except json.JSONDecodeError:
#                     continue

#                 etype = event.get("type", "")

#                 if etype == "session.created":
#                     print(f"[RT] ✅ Session ready", flush=True)

#                 elif etype == "input_audio_buffer.speech_started":
#                     print(f"[RT] [{ts()}] 🎙️  Speech started", flush=True)

#                 elif etype == "input_audio_buffer.speech_stopped":
#                     print(f"[RT] [{ts()}] 🎙️  Speech stopped — waiting for response", flush=True)

#                 elif etype == "conversation.item.input_audio_transcription.completed":
#                     transcript = event.get("transcript", "").strip()
#                     if transcript:
#                         print(f"[RT] [{ts()}] 📝 Transcript: {transcript}", flush=True)

#                 elif etype == "response.text.done":
#                     text = event.get("text", "").strip()
#                     if text:
#                         print(f"[RT] [{ts()}] 💬 Response: {text}", flush=True)
#                         threading.Thread(
#                             target=agent.text_to_speech,
#                             args=(text,),
#                             daemon=True,
#                         ).start()

#                 elif etype == "error":
#                     err = event.get("error", {})
#                     print(f"[RT] ❌ API error: {err.get('message', err)}", flush=True)

#         # ── VISION: Screen context updater ────────────────────────────────────
#         async def _update_context():
#             """
#             Runs every CONTEXT_CHECK_INTERVAL seconds.
#             If vision_worker has posted a new screen analysis, sends a session.update
#             to inject the updated screen context into the GPT Realtime session instructions.

#             This keeps the voice agent and the screen fully aligned.
#             The voice agent will naturally reference what is on screen in its next response.

#             Design notes:
#               - Runs concurrently with _send_audio() and _receive_events() via asyncio.gather()
#               - Never blocks: purely async, no thread synchronization needed
#               - session.update with only `instructions` is a partial update — does NOT
#                 reset VAD, turn_detection, modalities, or any other session settings
#               - If session_id is empty (standalone test run), this coroutine is a no-op
#             """
#             if not session_id:
#                 return  # Vision context not available without a session_id

#             import screen_context as ctx_store

#             while True:
#                 await asyncio.sleep(CONTEXT_CHECK_INTERVAL)

#                 try:
#                     # Only push update if the vision worker has posted new content
#                     if not ctx_store.has_new_context(session_id):
#                         continue

#                     # Build updated instructions: original system prompt + screen snippet
#                     screen_snippet = ctx_store.build_voice_injection(session_id)
#                     if not screen_snippet:
#                         # Context exists but is stale/low-confidence — skip
#                         ctx_store.mark_injected(session_id)
#                         continue

#                     updated_instructions = system_prompt + screen_snippet

#                     # Send partial session.update — only instructions field changes
#                     await ws.send(json.dumps({
#                         "type": "session.update",
#                         "session": {
#                             "instructions": updated_instructions,
#                         }
#                     }))

#                     # Mark as injected so we don't re-send the same context
#                     ctx_store.mark_injected(session_id)

#                     # Get summary for log (safe — context may have changed)
#                     ctx = ctx_store.get_context(session_id)
#                     summary_preview = ctx.last_summary[:60] if ctx else "?"
#                     print(
#                         f"[RT] 👁  [{sid8}] Screen context injected → \"{summary_preview}\"",
#                         flush=True,
#                     )

#                 except websockets.ConnectionClosed:
#                     break
#                 except asyncio.CancelledError:
#                     raise
#                 except Exception as e:
#                     print(f"[RT] ⚠️  [{sid8}] Context update error: {e}", flush=True)
#         # ── END VISION ────────────────────────────────────────────────────────

#         with sd.InputStream(
#             device=device_index,
#             samplerate=capture_rate,
#             channels=use_ch,
#             blocksize=blocksize,
#             dtype="float32",
#             callback=audio_callback,
#             latency="high",
#         ):
#             print(f"[RT] ✅ Listening on {pulse_source}", flush=True)
#             try:
#                 # Three coroutines running in parallel:
#                 #   _send_audio()      — audio capture → WebSocket
#                 #   _receive_events()  — WebSocket events → TTS
#                 #   _update_context()  — screen context → session.update  ← NEW
#                 await asyncio.gather(_send_audio(), _receive_events(), _update_context())
#             except asyncio.CancelledError:
#                 print(f"[RT] ✅ Stopped.", flush=True)
#                 raise










































#!/usr/bin/env python3
"""
realtime.py — GPT Realtime API (STT + LLM combined) — v2 Vision-aligned.

Flow:
  VSpk_{sid}.monitor (44100Hz)          ← per-session speaker sink monitor
  → resample to 24000Hz PCM16
  → RMS threshold filter
  → GPT Realtime WebSocket (STT + LLM)
  → text response
  → agent.text_to_speech()  (Cartesia Sonic-3)

VISION CHANGE (v2) — Dual injection:

  _update_context() is a third coroutine running alongside _send_audio()
  and _receive_events(). It checks the screen_context store every
  CONTEXT_CHECK_INTERVAL seconds and uses TWO different injection methods:

  Tier 1 — Live Event (conversation.item.create):
    When vision_worker detects a significant screen change (sharing started,
    stopped, or type changed), it sets has_live_event=True in screen_context.
    _update_context() picks this up and sends conversation.item.create with
    a [SCREEN EVENT] message. This message goes into conversation HISTORY —
    the model treats it as something that actually happened in the session.
    The model will naturally reference it in its next speech turn response.

    This is how the bot can answer "Can you see my screen?" correctly.

  Tier 2 — Background update (session.update instructions only):
    For non-significant screen updates (same type, minor content change),
    _update_context() sends session.update with only the `instructions` field
    updated. This silently refreshes the background context the model carries.
    It does NOT create a conversation history entry.

  Isolation:
    - Tier 1 fires FIRST if both flags are set simultaneously
    - After Tier 1 fires, Tier 2 is still processed on the next check cycle
    - Both marks are independently tracked and consumed
    - Neither blocks the audio pipeline
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
BARGE_IN_RMS  = 0.04

# How often to check screen_context store for new content (seconds)
# Reduced to 1.0s (was 3.0s) so live events land in conversation faster
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
    session_id: str = "",               # ← Required for vision context store access
):
    # ── Resolve per-session speaker sink ──────────────────────────────────────
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
    print(f"[RT] ⏱️  VAD     : semantic_vad, eagerness=high", flush=True)
    print(f"[RT] 🔈 Threshold: voice_threshold={voice_threshold} (RMS)", flush=True)
    print(f"[RT] 👁  Vision  : check_interval={CONTEXT_CHECK_INTERVAL}s (Tier1=live_event, Tier2=background)", flush=True)

    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview"
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    audio_q = queue.Queue(maxsize=500)
    loop    = asyncio.get_event_loop()

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[RT] ⚠️  {status}", flush=True)

        mono = np.mean(indata, axis=1) if indata.ndim > 1 else indata.flatten()

        if mute_flag.is_set():
            rms = float(np.sqrt(np.mean(np.square(mono))))
            if rms > BARGE_IN_RMS:
                print(f"[RT] [{ts()}] ⚡ Barge-in (rms={rms:.3f}) — stopping Alex", flush=True)
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

        # Initial session setup with full system prompt (includes vision capability block)
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "instructions": system_prompt,
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "high",
                    "create_response": True,
                    "interrupt_response": True,
                },
                "temperature": 0.8,
                "max_response_output_tokens": 80,
            }
        }))

        # ── Coroutine 1: Audio sender ─────────────────────────────────────────
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

        # ── Coroutine 2: Event receiver ───────────────────────────────────────
        async def _receive_events():
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "session.created":
                    print(f"[RT] ✅ Session ready", flush=True)

                elif etype == "input_audio_buffer.speech_started":
                    print(f"[RT] [{ts()}] 🎙️  Speech started", flush=True)

                elif etype == "input_audio_buffer.speech_stopped":
                    print(f"[RT] [{ts()}] 🎙️  Speech stopped — waiting for response", flush=True)

                elif etype == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "").strip()
                    if transcript:
                        print(f"[RT] [{ts()}] 📝 Transcript: {transcript}", flush=True)

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
                    print(f"[RT] ❌ API error: {err.get('message', err)}", flush=True)

        # ── Coroutine 3: Screen context updater (dual-tier) ───────────────────
        async def _update_context():
            """
            Checks the screen_context store every CONTEXT_CHECK_INTERVAL seconds.
            Uses two injection tiers to keep voice and vision aligned:

            Tier 1 — conversation.item.create (Live Event):
              Fired when vision_worker detects a significant change (sharing started/
              stopped, or content type changed). Injects a [SCREEN EVENT] message
              directly into conversation history. The model sees this as something
              that "happened" in the session — not background context.

              This is what allows the bot to answer "Can you see my screen?" correctly.
              The model doesn't just have a note in its instructions — it has a
              witnessed event in conversation history that it can refer back to.

              Important: conversation.item.create does NOT trigger a response by itself.
              The model uses the context on the candidate's next speech turn.

            Tier 2 — session.update instructions (Background):
              Fired for any new context (including after Tier 1 events). Updates the
              background system prompt with the current screen state. Persists across
              all future turns without creating a conversation history entry.

            Both tiers are checked every cycle. Tier 1 fires first if both are pending.
            """
            if not session_id:
                # No session_id — running standalone, vision context not available
                return

            import screen_context as ctx_store

            while True:
                await asyncio.sleep(CONTEXT_CHECK_INTERVAL)

                try:
                    # ── Tier 1: Live event ─────────────────────────────────────
                    has_event, event_text = ctx_store.get_live_event(session_id)

                    if has_event and event_text:
                        # Inject [SCREEN EVENT] into conversation history
                        await ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": event_text,
                                    }
                                ],
                            }
                        }))

                        ctx_store.mark_live_event_consumed(session_id)

                        # Log first 80 chars of event for visibility
                        preview = event_text.replace("\n", " ")[:80]
                        print(
                            f"[RT] 🔔 [{sid8}] Tier1 live event injected → \"{preview}\"",
                            flush=True,
                        )

                    # ── Tier 2: Background context ─────────────────────────────
                    if ctx_store.has_new_context(session_id):
                        screen_snippet = ctx_store.build_voice_injection(session_id)

                        if screen_snippet:
                            # Partial session.update — only instructions changes.
                            # Does NOT reset VAD, turn_detection, modalities, or tokens.
                            updated_instructions = system_prompt + screen_snippet

                            await ws.send(json.dumps({
                                "type": "session.update",
                                "session": {
                                    "instructions": updated_instructions,
                                }
                            }))

                            ctx_store.mark_injected(session_id)

                            ctx = ctx_store.get_context(session_id)
                            summary_preview = ctx.last_summary[:60] if ctx else "?"
                            print(
                                f"[RT] 👁  [{sid8}] Tier2 background updated → \"{summary_preview}\"",
                                flush=True,
                            )
                        else:
                            # Context exists but stale/low-confidence — clear the flag
                            ctx_store.mark_injected(session_id)

                except websockets.ConnectionClosed:
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[RT] ⚠️  [{sid8}] Context update error: {e}", flush=True)

        # ── Run all three coroutines concurrently ─────────────────────────────
        with sd.InputStream(
            device=device_index,
            samplerate=capture_rate,
            channels=use_ch,
            blocksize=blocksize,
            dtype="float32",
            callback=audio_callback,
            latency="high",
        ):
            print(f"[RT] ✅ Listening on {pulse_source}", flush=True)
            try:
                await asyncio.gather(
                    _send_audio(),
                    _receive_events(),
                    _update_context(),      # ← Vision: Tier 1 + Tier 2 dual injection
                )
            except asyncio.CancelledError:
                print(f"[RT] ✅ Stopped.", flush=True)
                raise
#!/usr/bin/env python3
"""
realtime.py — GPT Realtime API (STT + LLM combined)

Flow:
  VSpk_{sid}.monitor (44100Hz)          ← per-session speaker sink monitor
  → resample to 24000Hz PCM16
  → RMS threshold filter
  → GPT Realtime WebSocket (STT + LLM)
  → text response
  → agent.text_to_speech()  (Cartesia Sonic-3)

FIX: PULSE_SOURCE is now read from PULSE_SPK_SINK env var (set per-session
     by api.py) instead of being hardcoded to VirtualSpeaker.monitor.
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
):
    # ── FIX: resolve per-session speaker sink from env ─────────────────────
    # api.py sets PULSE_SPK_SINK = VSpk_{sid8} for each session.
    # We need to listen on its .monitor to capture Chrome's speaker output
    # (= candidate's voice coming from Meet).
    # Fallback chain: PULSE_SPK_SINK → PULSE_SOURCE → global fallback
    spk_sink = (
        os.getenv("PULSE_SPK_SINK")         # per-session: VSpk_2fad6aeb
        or os.getenv("PULSE_SOURCE")         # legacy fallback
        or "VirtualSpeaker"                  # last resort
    )
    # The .monitor of the speaker sink is where Chrome's audio output appears
    pulse_source = f"{spk_sink}.monitor"

    os.environ["PULSE_SOURCE"] = pulse_source
    print(f"[RT] 🔌 PULSE_SOURCE: {pulse_source}", flush=True)
    # ── END FIX ────────────────────────────────────────────────────────────

    device_info  = sd.query_devices(device_index)
    capture_rate = int(device_info.get("default_samplerate", CAPTURE_RATE))
    max_ch       = int(device_info.get("max_input_channels", 2))
    use_ch       = min(max_ch, 2)
    blocksize    = int(capture_rate * FRAME_MS / 1000)

    print(f"[RT] 🤖 Model   : gpt-4o-mini-realtime-preview (STT + LLM)", flush=True)
    print(f"[RT] 🎙️  Device  : [{device_index}] {device_info['name']} @ {capture_rate}Hz", flush=True)
    print(f"[RT] ⏱️  VAD     : semantic_vad, eagerness=high", flush=True)
    print(f"[RT] 🔈 Threshold: voice_threshold={voice_threshold} (RMS)", flush=True)

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
                await asyncio.gather(_send_audio(), _receive_events())
            except asyncio.CancelledError:
                print(f"[RT] ✅ Stopped.", flush=True)
                raise
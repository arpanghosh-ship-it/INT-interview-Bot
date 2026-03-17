# updated realtime_whisper_stt_env.py-


#!/usr/bin/env python3
"""
realtime_whisper_stt_env.py

Capture VB-Cable audio, detect utterances (RMS VAD), buffer each utterance,
save WAV and send to OpenAI Whisper for transcription.
"""
import argparse
import os
import queue
import threading
import time
import tempfile
import wave
from pathlib import Path
from typing import List

import numpy as np
import requests
import sounddevice as sd
from dotenv import load_dotenv

# ── Config defaults ────────────────────────────────────────────────────────────
DEFAULT_FRAME_MS     = 30
DEFAULT_SILENCE_SEC  = 0.8
DEFAULT_RMS_THRESHOLD = 0.02
SMOOTH_FRAMES        = 3
OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
REQUEST_TIMEOUT      = 120
UTTERANCE_FOLDER     = Path("utterances")
# ──────────────────────────────────────────────────────────────────────────────


def load_api_key():
    load_dotenv()
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env or environment.")
    return key


def float32_to_int16_bytes(sig: np.ndarray) -> bytes:
    clipped = np.clip(sig, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def save_wav_mono(path: str, data: np.ndarray, samplerate: int):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(float32_to_int16_bytes(data))


def transcribe(wav_path: str, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        resp = requests.post(
            OPENAI_TRANSCRIBE_URL,
            headers=headers,
            data={"model": "whisper-1"},
            files=files,
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def ts():
    return time.strftime("%H:%M:%S")


def log(msg: str):
    """Print with [STT] prefix — matches main.py style."""
    print(f"[STT]  [{ts()}] {msg}", flush=True)


# ── Worker thread ──────────────────────────────────────────────────────────────
def worker_loop(
    q: queue.Queue,
    samplerate: int,
    silence_sec: float,
    rms_threshold: float,
    api_key: str,
    stop_event: threading.Event,
    dry_run: bool,
):
    buffer_frames: List[np.ndarray] = []
    is_recording  = False
    last_voice_ts = 0.0
    rms_window: List[float] = []

    UTTERANCE_FOLDER.mkdir(exist_ok=True)

    while True:
        # ── Get frame ──────────────────────────────────────────────────────────
        try:
            frame = q.get(timeout=0.5)
        except queue.Empty:
            if stop_event.is_set():
                # Finalize any remaining audio on shutdown
                if is_recording and buffer_frames:
                    _finalize(buffer_frames, samplerate, api_key, dry_run)
                break
            continue

        # ── RMS voice activity detection ───────────────────────────────────────
        rms_val = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        rms_window.append(rms_val)
        if len(rms_window) > SMOOTH_FRAMES:
            rms_window.pop(0)
        smooth_rms = sum(rms_window) / len(rms_window)

        now = time.time()

        if smooth_rms >= rms_threshold:
            last_voice_ts = now
            if not is_recording:
                is_recording  = True
                buffer_frames = [frame]
                log(f"🎙️  Recording... rms={smooth_rms:.4f}")
            else:
                buffer_frames.append(frame)
        else:
            if is_recording:
                buffer_frames.append(frame)
                if now - last_voice_ts > silence_sec:
                    # Utterance ended
                    _finalize(buffer_frames, samplerate, api_key, dry_run)
                    buffer_frames = []
                    is_recording  = False
                    log("💤 Idle")


def _finalize(buffer_frames, samplerate, api_key, dry_run):
    """Save WAV, transcribe, print result."""
    audio_np = np.concatenate(buffer_frames)

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".wav", dir=str(UTTERANCE_FOLDER)
    ) as tmp:
        wav_path = tmp.name

    save_wav_mono(wav_path, audio_np, samplerate)

    if dry_run:
        log(f"🗂️  DRY-RUN — saved {wav_path}")
        return

    log("📝 Transcribing...")
    try:
        text = transcribe(wav_path, api_key)
        if text:
            log(f"💬 TRANSCRIPT: {text}")
        else:
            log("💬 TRANSCRIPT: (empty)")
    except Exception as e:
        log(f"❌ STT error: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="VB-Cable → OpenAI Whisper real-time transcription"
    )
    parser.add_argument("--device",    type=int,   required=True,
                        help="sounddevice input index (CABLE Output)")
    parser.add_argument("--frame_ms",  type=int,   default=DEFAULT_FRAME_MS)
    parser.add_argument("--silence",   type=float, default=DEFAULT_SILENCE_SEC)
    parser.add_argument("--threshold", type=float, default=DEFAULT_RMS_THRESHOLD)
    parser.add_argument("--dry-run",   action="store_true",
                        help="Save WAVs without calling OpenAI")
    args = parser.parse_args()

    dry_run = bool(args.dry_run)
    api_key = None if dry_run else load_api_key()

    # ── Device info ────────────────────────────────────────────────────────────
    device_info  = sd.query_devices(args.device)
    samplerate   = int(device_info.get("default_samplerate", 44100))
    max_channels = int(device_info.get("max_input_channels", 1))
    use_channels = min(max_channels, 2)
    blocksize    = int(samplerate * (args.frame_ms / 1000.0))

    print(f"[STT]  🎙️  Device  : {device_info['name']}", flush=True)
    print(f"[STT]  🎙️  Rate    : {samplerate}Hz | Channels: {use_channels}", flush=True)
    print(f"[STT]  🎙️  Threshold: {args.threshold} | Silence: {args.silence}s", flush=True)

    # ── Start worker thread ────────────────────────────────────────────────────
    q          = queue.Queue(maxsize=500)
    stop_event = threading.Event()

    worker = threading.Thread(
        target=worker_loop,
        args=(q, samplerate, args.silence, args.threshold, api_key, stop_event, dry_run),
        daemon=False,
    )
    worker.start()
    log("✅ Worker started. Listening for speech...")

    # ── Audio callback ─────────────────────────────────────────────────────────
    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[STT]  ⚠️  {status}", flush=True)
        mono = np.mean(indata, axis=1) if indata.ndim > 1 else indata.flatten()
        try:
            q.put_nowait(mono.copy())
        except queue.Full:
            pass  # drop frame — queue full

    # ── Open audio stream ──────────────────────────────────────────────────────
    try:
        with sd.InputStream(
            device=args.device,
            samplerate=samplerate,
            channels=use_channels,
            blocksize=blocksize,
            dtype="float32",
            callback=audio_callback,
            latency="high",
        ):
            print(f"[STT]  ✅ Listening on VB-Cable Output. Ctrl+C to stop.", flush=True)
            try:
                while True:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                print(f"\n[STT]  👋 Stopping...", flush=True)
                stop_event.set()
                worker.join(timeout=30.0)
                print(f"[STT]  ✅ Worker stopped.", flush=True)

    except Exception as e:
        print(f"[STT]  ❌ Stream error: {e}", flush=True)
        stop_event.set()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
llm_tts.py — TTS (Cartesia Sonic-3) + Barge-in + Greeting

Multi-session change: `pulse_sink` is now a parameter (not hardcoded).
Each session passes its own isolated sink name so TTS audio is isolated.

LLM is handled by realtime.py (GPT Realtime WebSocket).
This file only does:
  1. text_to_speech()  — Cartesia → paplay → {pulse_sink} → Chrome mic → Meet
  2. interrupt()       — barge-in: kills paplay mid-sentence
  3. greet()           — one-off REST call to GPT-4o-mini for opening greeting
"""

import os
import subprocess
import tempfile
import threading
import time

from cartesia import Cartesia
from openai import OpenAI


class InterviewerAgent:
    def __init__(
        self,
        openai_api_key: str,
        cartesia_api_key: str,
        system_prompt: str,
        tts_device_index: int = 0,
        cartesia_voice_id: str = "694f9389-aac1-45b6-b726-9d9369183238",
        cartesia_model: str = "sonic-3",
        mute_flag: threading.Event = None,
        post_tts_cooldown: float = 1.0,
        pulse_sink: str = None,          # ← per-session sink name
    ):
        # OpenAI client used ONLY for greet() — one REST call at session start
        self._openai_client     = OpenAI(api_key=openai_api_key)
        self._cartesia_client   = Cartesia(api_key=cartesia_api_key)
        self._system_prompt     = system_prompt
        self._cartesia_voice_id = cartesia_voice_id
        self._cartesia_model    = cartesia_model
        self._mute_flag         = mute_flag
        self._post_tts_cooldown = post_tts_cooldown
        self._speaking_lock     = threading.Lock()

        # Resolve pulse sink: param → env → fallback
        self._pulse_sink = (
            pulse_sink
            or os.getenv("PULSE_MIC_SINK")
            or os.getenv("PULSE_SINK")
            or "VirtualMic"
        )

        # Barge-in state
        self._paplay_proc: subprocess.Popen | None = None
        self._interrupted = False

        print(f"[LLM_TTS] ✅ InterviewerAgent ready.", flush=True)
        print(f"[LLM_TTS]    TTS      : Cartesia {cartesia_model}", flush=True)
        print(f"[LLM_TTS]    Voice    : {cartesia_voice_id}", flush=True)
        print(f"[LLM_TTS]    Sink     : {self._pulse_sink} → Chrome mic → Meet", flush=True)
        print(f"[LLM_TTS]    LLM      : GPT Realtime (realtime.py)", flush=True)
        print(f"[LLM_TTS]    Barge-in : ✅ Enabled", flush=True)

    # ── Barge-in: called by realtime.py when user speaks during TTS ───────────
    def interrupt(self):
        if self._paplay_proc and self._paplay_proc.poll() is None:
            print(f"[LLM_TTS] ⚡ Barge-in — stopping bot mid-sentence", flush=True)
            self._paplay_proc.terminate()
            self._interrupted = True

    # ── TTS ───────────────────────────────────────────────────────────────────
    def text_to_speech(self, text: str):
        """
        Cartesia → WAV bytes → paplay → {pulse_sink} → Chrome mic → Meet
        Each session writes to its own isolated PulseAudio sink.
        """
        print(f"[LLM_TTS] 🔊 TTS [{self._pulse_sink}] → {text[:80]}", flush=True)

        audio_chunks = self._cartesia_client.tts.bytes(
            model_id=self._cartesia_model,
            transcript=text,
            voice={"mode": "id", "id": self._cartesia_voice_id},
            language="en",
            output_format={
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": 44100,
            },
        )

        audio_bytes = b"".join(audio_chunks)
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, dir="/tmp"
            ) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            with self._speaking_lock:
                self._interrupted = False

                # Mute STT before playback (prevents echo)
                if self._mute_flag:
                    self._mute_flag.set()

                try:
                    # Popen (not run) so interrupt() can terminate it mid-sentence
                    self._paplay_proc = subprocess.Popen(
                        ["paplay", f"--device={self._pulse_sink}", tmp_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._paplay_proc.wait()
                    self._paplay_proc = None

                finally:
                    cooldown = 0.2 if self._interrupted else self._post_tts_cooldown
                    time.sleep(cooldown)
                    if self._mute_flag:
                        self._mute_flag.clear()

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        status = "⚡ Interrupted" if self._interrupted else "✅ Done speaking"
        print(f"[LLM_TTS] {status}", flush=True)

    # ── Greeting ──────────────────────────────────────────────────────────────
    def greet(self):
        """One-off REST call to GPT-4o-mini for the opening greeting."""
        print(f"[LLM_TTS] 👋 Generating greeting...", flush=True)

        response = self._openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        "[SYSTEM: Session just started. Introduce yourself using your "
                        "name and role. Do NOT use placeholders. Greet warmly, ask "
                        "candidate to introduce themselves. Max 2-3 sentences.]"
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=100,
        )

        greeting = response.choices[0].message.content.strip()
        print(f"[LLM_TTS] 💬 Greeting → {greeting}", flush=True)
        self.text_to_speech(greeting)

    # ── respond_to: kept for API compatibility ────────────────────────────────
    def respond_to(self, transcript: str):
        """Not used with GPT Realtime — realtime.py calls text_to_speech() directly."""
        pass
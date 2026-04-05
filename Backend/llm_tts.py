#!/usr/bin/env python3
"""
llm_tts.py — TTS (Cartesia Sonic-3) + Barge-in + Greeting (v4)

KEY CHANGE FROM v3:
─────────────────────────────────────────────────────────────────────
The greet() function now uses a SEPARATE minimal greeting_prompt
instead of self._system_prompt (the full master prompt).

Why this was broken:
  The master system prompt (v3+) contains this rule:
  "GREETING ALREADY DELIVERED: Do not re-introduce yourself.
   Do not say your name again."
  When greet() passed the full system prompt to GPT-4o-mini, GPT followed
  that rule and suppressed the bot's name from the greeting.
  Result: "I'm glad to have you here today." (no name mentioned at all)

How it's fixed:
  A separate greeting_prompt is passed to InterviewerAgent.__init__().
  It contains only the bot's identity info and a clear instruction to
  deliver a proper opening greeting with the name included.
  build_greeting_prompt() in make_prompt.py generates this.
  Result: "Hi there, I'm Alex, your interviewer for today's Technical
           interview. Could you start by introducing yourself?"

Other changes:
  - Thread-safe interrupt() fix retained from v3 (TOCTOU race fix)
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
        greeting_prompt: str = "",          # ← NEW: separate prompt for greet()
        tts_device_index: int = 0,
        cartesia_voice_id: str = "694f9389-aac1-45b6-b726-9d9369183238",
        cartesia_model: str = "sonic-3",
        mute_flag: threading.Event = None,
        post_tts_cooldown: float = 1.0,
        pulse_sink: str = None,
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

        # The greeting prompt is separate from the master system prompt.
        # If not provided, fall back to a generic greeting instruction.
        self._greeting_prompt = greeting_prompt or (
            "You are an AI interviewer. Deliver a warm opening greeting. "
            "Introduce yourself by name. Ask the candidate to introduce themselves. "
            "Maximum 2 sentences. Plain speech only, no markdown."
        )

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
        print(f"[LLM_TTS]    Barge-in : ✅ Enabled (thread-safe)", flush=True)

    # ── Barge-in ──────────────────────────────────────────────────────────────
    def interrupt(self):
        """
        Thread-safe barge-in. TOCTOU race fix: copy to local variable first.
        Called from sounddevice audio callback thread while text_to_speech()
        may be running in a separate daemon thread.
        """
        proc = self._paplay_proc    # GIL-atomic read; local ref stays valid
        if proc is not None and proc.poll() is None:
            print(f"[LLM_TTS] ⚡ Barge-in — stopping bot mid-sentence", flush=True)
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass
            self._interrupted = True

    # ── TTS ───────────────────────────────────────────────────────────────────
    def text_to_speech(self, text: str):
        """
        Cartesia → WAV bytes → paplay → {pulse_sink} → Chrome mic → Meet
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

                if self._mute_flag:
                    self._mute_flag.set()

                try:
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
        """
        One-off REST call to GPT-4o-mini for the opening greeting.

        IMPORTANT: Uses self._greeting_prompt (the minimal identity-only prompt),
        NOT self._system_prompt (the full master prompt).

        The master prompt contains "GREETING ALREADY DELIVERED: Do not re-introduce
        yourself" which would prevent GPT from saying the bot's name. The separate
        greeting_prompt has no such restriction, so the bot correctly introduces
        itself by name.
        """
        print(f"[LLM_TTS] 👋 Generating greeting...", flush=True)

        response = self._openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": self._greeting_prompt,   # ← uses separate greeting prompt
                },
                {
                    "role": "user",
                    "content": "[Deliver your opening greeting now.]",
                },
            ],
            temperature=0.5,
            max_tokens=80,
        )

        greeting = response.choices[0].message.content.strip()
        print(f"[LLM_TTS] 💬 Greeting → {greeting}", flush=True)
        self.text_to_speech(greeting)

    # ── respond_to: kept for API compatibility ────────────────────────────────
    def respond_to(self, transcript: str):
        """Not used with GPT Realtime — realtime.py calls text_to_speech() directly."""
        pass
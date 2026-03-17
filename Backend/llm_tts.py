# #!/usr/bin/env python3
# """
# llm_tts.py
# Pipeline: transcript → GPT-4o-mini → Cartesia Sonic-3 TTS → VirtualMic → Chrome mic → Meet
# """

# import io
# import os
# import subprocess
# import tempfile
# import threading
# import time

# import numpy as np
# import soundfile as sf
# from openai import OpenAI
# from cartesia import Cartesia


# class InterviewerAgent:
#     def __init__(
#         self,
#         openai_api_key: str,
#         cartesia_api_key: str,
#         system_prompt: str,
#         tts_device_index: int,          # kept for compatibility but not used for routing
#         cartesia_voice_id: str = "694f9389-aac1-45b6-b726-9d9369183238",
#         cartesia_model: str = "sonic-3",
#         mute_flag: threading.Event = None,
#         post_tts_cooldown: float = 1.0,
#     ):
#         self.llm_client         = OpenAI(api_key=openai_api_key)
#         self.cartesia_client    = Cartesia(api_key=cartesia_api_key)
#         self.system_prompt      = system_prompt
#         self.cartesia_voice_id  = cartesia_voice_id
#         self.cartesia_model     = cartesia_model
#         self._mute_flag         = mute_flag
#         self._post_tts_cooldown = post_tts_cooldown
#         self.conversation_history = []
#         self._speaking_lock     = threading.Lock()

#         print(f"[LLM_TTS] ✅ InterviewerAgent ready.", flush=True)
#         print(f"[LLM_TTS]    LLM            : gpt-4o-mini", flush=True)
#         print(f"[LLM_TTS]    TTS            : Cartesia {cartesia_model}", flush=True)
#         print(f"[LLM_TTS]    Voice ID       : {cartesia_voice_id}", flush=True)
#         print(f"[LLM_TTS]    TTS sink       : VirtualMic (→ Chrome mic → Meet)", flush=True)
#         print(f"[LLM_TTS]    Post-TTS wait  : {post_tts_cooldown}s", flush=True)

#     # ── Step 1: LLM ───────────────────────────────────────────────────────────
#     def get_llm_response(self, user_text: str) -> str:
#         self.conversation_history.append({"role": "user", "content": user_text})
#         messages = [{"role": "system", "content": self.system_prompt}] + self.conversation_history

#         print(f"[LLM_TTS] 🧠 GPT-4o-mini ←\n{user_text}", flush=True)

#         response = self.llm_client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=messages,
#             temperature=0.7,
#         )

#         assistant_text = response.choices[0].message.content.strip()
#         self.conversation_history.append({"role": "assistant", "content": assistant_text})

#         print(f"[LLM_TTS] 💬 GPT-4o-mini →\n{assistant_text}", flush=True)
#         return assistant_text

#     # ── Step 2: TTS ───────────────────────────────────────────────────────────
#     def text_to_speech(self, text: str):
#         print(f"[LLM_TTS] 🔊 Cartesia TTS generating audio...", flush=True)

#         audio_chunks = self.cartesia_client.tts.bytes(
#             model_id=self.cartesia_model,
#             transcript=text,
#             voice={"mode": "id", "id": self.cartesia_voice_id},
#             language="en",
#             output_format={
#                 "container": "wav",
#                 "encoding": "pcm_s16le",
#                 "sample_rate": 44100,
#             },
#         )

#         # Save raw WAV bytes from Cartesia to temp file
#         audio_bytes = b"".join(audio_chunks)
#         tmp_path = None

#         try:
#             with tempfile.NamedTemporaryFile(
#                 suffix=".wav", delete=False, dir="/tmp"
#             ) as f:
#                 f.write(audio_bytes)
#                 tmp_path = f.name

#             print(
#                 f"[LLM_TTS] ▶️  Playing via paplay → VirtualMic → Chrome mic → Meet",
#                 flush=True
#             )

#             with self._speaking_lock:
#                 if self._mute_flag:
#                     self._mute_flag.set()
#                 try:
#                     # ── KEY FIX: paplay explicitly targets VirtualMic ──────────
#                     # VirtualMic.monitor = Chrome's microphone
#                     # Meet participants hear this audio
#                     result = subprocess.run(
#                         ["paplay", "--device=VirtualMic", tmp_path],
#                         capture_output=True,
#                         text=True,
#                         timeout=60,
#                     )
#                     if result.returncode != 0:
#                         print(f"[LLM_TTS] ⚠️  paplay error: {result.stderr}", flush=True)
#                 finally:
#                     if self._post_tts_cooldown > 0:
#                         time.sleep(self._post_tts_cooldown)
#                     if self._mute_flag:
#                         self._mute_flag.clear()

#         finally:
#             if tmp_path and os.path.exists(tmp_path):
#                 os.unlink(tmp_path)

#         print(f"[LLM_TTS] ✅ Done speaking.", flush=True)

#     # ── Greeting ──────────────────────────────────────────────────────────────
#     def greet(self):
#         print(f"[LLM_TTS] 👋 Sending greeting trigger...", flush=True)

#         messages = [
#             {"role": "system", "content": self.system_prompt},
#             {
#                 "role": "user",
#                 "content": (
#                     "[SYSTEM: The interview session has just started. "
#                     "Introduce yourself using the name and role defined in your instructions. "
#                     "Do NOT use placeholders like [Your Name]. "
#                     "Greet the candidate warmly and ask them to introduce themselves.]"
#                 )
#             },
#         ]

#         response = self.llm_client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=messages,
#             temperature=0.7,
#         )

#         greeting_text = response.choices[0].message.content.strip()
#         self.conversation_history.append({"role": "assistant", "content": greeting_text})

#         print(f"[LLM_TTS] 💬 Greeting →\n{greeting_text}", flush=True)
#         self.text_to_speech(greeting_text)

#     # ── Full pipeline ─────────────────────────────────────────────────────────
#     def respond_to(self, transcript: str):
#         if not transcript or len(transcript.strip()) < 2:
#             return
#         try:
#             response_text = self.get_llm_response(transcript)
#             self.text_to_speech(response_text)
#         except Exception as e:
#             print(f"[LLM_TTS] ❌ Error: {e}", flush=True)




















#!/usr/bin/env python3
"""
llm_tts.py — TTS (Cartesia Sonic-3) + Barge-in + Greeting

LLM is now handled by realtime.py (GPT Realtime WebSocket).
This file only does:
  1. text_to_speech()  — Cartesia → paplay → VirtualMic → Meet
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
        tts_device_index: int = 0,          # kept for API compatibility
        cartesia_voice_id: str = "694f9389-aac1-45b6-b726-9d9369183238",
        cartesia_model: str = "sonic-3",
        mute_flag: threading.Event = None,
        post_tts_cooldown: float = 1.0,
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

        # Barge-in state
        self._paplay_proc: subprocess.Popen | None = None
        self._interrupted = False

        print(f"[LLM_TTS] ✅ InterviewerAgent ready.", flush=True)
        print(f"[LLM_TTS]    TTS      : Cartesia {cartesia_model}", flush=True)
        print(f"[LLM_TTS]    Voice    : {cartesia_voice_id}", flush=True)
        print(f"[LLM_TTS]    Sink     : VirtualMic → Chrome mic → Meet", flush=True)
        print(f"[LLM_TTS]    LLM      : GPT Realtime (realtime.py)", flush=True)
        print(f"[LLM_TTS]    Barge-in : ✅ Enabled", flush=True)

    # ── Barge-in: called by realtime.py when user speaks during TTS ───────────
    def interrupt(self):
        if self._paplay_proc and self._paplay_proc.poll() is None:
            print(f"[LLM_TTS] ⚡ Barge-in — stopping Alex mid-sentence", flush=True)
            self._paplay_proc.terminate()
            self._interrupted = True

    # ── TTS ───────────────────────────────────────────────────────────────────
    def text_to_speech(self, text: str):
        """
        Called by realtime.py on each response.
        Cartesia → WAV bytes → paplay → VirtualMic → Chrome mic → Meet
        """
        print(f"[LLM_TTS] 🔊 TTS → {text[:80]}", flush=True)

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

                # Mute STT before playback
                if self._mute_flag:
                    self._mute_flag.set()

                try:
                    # Popen (not run) — so interrupt() can terminate it
                    self._paplay_proc = subprocess.Popen(
                        ["paplay", "--device=VirtualMic", tmp_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._paplay_proc.wait()   # blocks until done OR killed
                    self._paplay_proc = None

                finally:
                    # Shorter cooldown if interrupted
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
        Realtime WebSocket is not open yet at this point.
        After greeting, realtime.py takes over for all responses.
        """
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
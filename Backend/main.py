# #!/usr/bin/env python3
# """
# main.py — Single entry point.
# Pipeline: Join Meet → Greeting → Capture audio → STT → LLM → TTS → Meet mic
# """

# import asyncio
# import os
# import queue
# import sys
# import tempfile
# import threading
# import time
# import wave
# from pathlib import Path

# import numpy as np
# import sounddevice as sd
# from dotenv import load_dotenv

# from join_meet import run_meet              # ✅ Correct
# from llm_tts import InterviewerAgent        # ✅ Correct

# load_dotenv()

# # ── Config ────────────────────────────────────────────────────────────────────
# OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
# CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY")
# CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "694f9389-aac1-45b6-b726-9d9369183238")
# STT_DEVICE_INDEX  = int(os.getenv("STT_DEVICE_INDEX", "0"))
# TTS_DEVICE_INDEX  = int(os.getenv("TTS_DEVICE_INDEX", "0"))
# RMS_THRESHOLD     = float(os.getenv("STT_RMS_THRESHOLD", "0.02"))
# SILENCE_SEC       = float(os.getenv("STT_SILENCE_SEC", "1.5"))
# POST_TTS_COOLDOWN = float(os.getenv("POST_TTS_COOLDOWN", "1.0"))

# FRAME_MS          = 30
# SMOOTH_FRAMES     = 3
# UTTERANCE_FOLDER  = Path("utterances")

# SYSTEM_PROMPT = os.getenv(
#     "SYSTEM_PROMPT",
#     "You are Alex, a professional AI technical interviewer at INT Technologies. "
#     "Keep your responses concise and conversational."
# )

# # ── STT helpers ───────────────────────────────────────────────────────────────
# def float32_to_int16_bytes(sig: np.ndarray) -> bytes:
#     clipped = np.clip(sig, -1.0, 1.0)
#     return (clipped * 32767.0).astype(np.int16).tobytes()


# def save_wav_mono(path: str, data: np.ndarray, samplerate: int):
#     with wave.open(path, "wb") as wf:
#         wf.setnchannels(1)
#         wf.setsampwidth(2)
#         wf.setframerate(samplerate)
#         wf.writeframes(float32_to_int16_bytes(data))


# def transcribe_wav(wav_path: str, api_key: str) -> str:
#     from openai import OpenAI
#     client = OpenAI(api_key=api_key)
#     with open(wav_path, "rb") as f:
#         result = client.audio.transcriptions.create(model="whisper-1", file=f)
#     return result.text.strip()


# def ts():
#     return time.strftime("%H:%M:%S")


# # ── STT Worker ────────────────────────────────────────────────────────────────
# def stt_worker(
#     audio_queue: queue.Queue,
#     samplerate: int,
#     agent: InterviewerAgent,
#     api_key: str,
#     stop_event: threading.Event,
#     mute_flag: threading.Event,
# ):
#     UTTERANCE_FOLDER.mkdir(exist_ok=True)
#     buffer_frames = []
#     is_recording  = False
#     last_voice_ts = 0.0
#     rms_window    = []

#     print(f"[STT]  ✅ Worker started. Listening for speech...", flush=True)

#     while True:
#         try:
#             frame = audio_queue.get(timeout=0.5)
#         except queue.Empty:
#             if stop_event.is_set():
#                 if is_recording and buffer_frames:
#                     _finalize_utterance(buffer_frames, samplerate, agent, api_key)
#                 break
#             continue

#         if mute_flag.is_set():
#             buffer_frames = []
#             is_recording  = False
#             continue

#         rms_val = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
#         rms_window.append(rms_val)
#         if len(rms_window) > SMOOTH_FRAMES:
#             rms_window.pop(0)
#         smooth_rms = sum(rms_window) / len(rms_window)

#         now = time.time()

#         if smooth_rms >= RMS_THRESHOLD:
#             last_voice_ts = now
#             if not is_recording:
#                 is_recording  = True
#                 buffer_frames = [frame]
#                 print(f"[STT]  [{ts()}] 🎙️  Recording... rms={smooth_rms:.4f}", flush=True)
#             else:
#                 buffer_frames.append(frame)
#         else:
#             if is_recording:
#                 buffer_frames.append(frame)
#                 if now - last_voice_ts > SILENCE_SEC:
#                     _finalize_utterance(buffer_frames, samplerate, agent, api_key)
#                     buffer_frames = []
#                     is_recording  = False
#                     print(f"[STT]  [{ts()}] 💤 Idle", flush=True)


# def _finalize_utterance(buffer_frames, samplerate, agent, api_key):
#     audio_np = np.concatenate(buffer_frames)
#     with tempfile.NamedTemporaryFile(
#         delete=False, suffix=".wav", dir=str(UTTERANCE_FOLDER)
#     ) as tmp:
#         wav_path = tmp.name

#     save_wav_mono(wav_path, audio_np, samplerate)
#     print(f"[STT]  [{ts()}] 📝 Transcribing...", flush=True)

#     try:
#         transcript = transcribe_wav(wav_path, api_key)
#         print(f"[STT]  [{ts()}] 💬 TRANSCRIPT: {transcript}", flush=True)

#         if transcript and len(transcript.strip()) > 1:
#             threading.Thread(
#                 target=agent.respond_to,
#                 args=(transcript,),
#                 daemon=True
#             ).start()
#         else:
#             print(f"[STT]  [{ts()}] ⏭️  Skipped empty transcript", flush=True)

#     except Exception as e:
#         print(f"[STT]  [{ts()}] ❌ Error: {e}", flush=True)


# # ── Run STT ───────────────────────────────────────────────────────────────────
# async def run_stt(agent: InterviewerAgent, mute_flag: threading.Event):

#     # ── KEY FIX: Tell PulseAudio to capture from VirtualSpeaker.monitor ───────
#     # VirtualSpeaker.monitor = Chrome's audio output (Meet audio from participants)
#     # Without this, STT captures from VirtualMic.monitor (TTS echo = feedback loop)
#     os.environ["PULSE_SOURCE"] = "VirtualSpeaker.monitor"
#     print(f"[STT]  🔌 Capturing from: VirtualSpeaker.monitor (Chrome speaker output)", flush=True)

#     device_info  = sd.query_devices(STT_DEVICE_INDEX)
#     samplerate   = int(device_info.get("default_samplerate", 44100))
#     max_channels = int(device_info.get("max_input_channels", 2))
#     use_channels = min(max_channels, 2)
#     blocksize    = int(samplerate * (FRAME_MS / 1000.0))

#     print(f"[STT]  🎙️  Device  : {device_info['name']}", flush=True)
#     print(f"[STT]  🎙️  Rate    : {samplerate}Hz | Channels: {use_channels}", flush=True)
#     print(f"[STT]  🎙️  Silence : {SILENCE_SEC}s | RMS threshold: {RMS_THRESHOLD}", flush=True)

#     audio_queue = queue.Queue(maxsize=500)
#     stop_event  = threading.Event()

#     worker = threading.Thread(
#         target=stt_worker,
#         args=(audio_queue, samplerate, agent, OPENAI_API_KEY, stop_event, mute_flag),
#         daemon=False,
#     )
#     worker.start()

#     def audio_callback(indata, frames, time_info, status):
#         if status:
#             print(f"[STT]  ⚠️  {status}", flush=True)
#         mono = np.mean(indata, axis=1) if indata.ndim > 1 else indata.flatten()
#         try:
#             audio_queue.put_nowait(mono.copy())
#         except queue.Full:
#             pass

#     loop = asyncio.get_event_loop()

#     def run_stream():
#         with sd.InputStream(
#             device=STT_DEVICE_INDEX,
#             samplerate=samplerate,
#             channels=use_channels,
#             blocksize=blocksize,
#             dtype="float32",
#             callback=audio_callback,
#             latency="high",
#         ):
#             print(f"[STT]  ✅ Listening on VirtualSpeaker.monitor. Ctrl+C to stop.", flush=True)
#             stop_event.wait()

#     try:
#         await loop.run_in_executor(None, run_stream)
#     except asyncio.CancelledError:
#         stop_event.set()
#         worker.join(timeout=5.0)
#         raise
#     finally:
#         stop_event.set()
#         worker.join(timeout=5.0)
#         print("[STT]  ✅ Worker stopped.", flush=True)


# # ── Main ──────────────────────────────────────────────────────────────────────
# async def main():
#     if not OPENAI_API_KEY:
#         print("❌  OPENAI_API_KEY not set in .env", file=sys.stderr)
#         sys.exit(1)
#     if not CARTESIA_API_KEY:
#         print("❌  CARTESIA_API_KEY not set in .env", file=sys.stderr)
#         sys.exit(1)

#     print("=" * 60, flush=True)
#     print("   🤖 INT Avatar Interview System", flush=True)
#     print("=" * 60, flush=True)
#     print(f"[MAIN] STT device      : {STT_DEVICE_INDEX} (CABLE Output)", flush=True)
#     print(f"[MAIN] TTS device      : {TTS_DEVICE_INDEX} (CABLE Input)", flush=True)
#     print(f"[MAIN] Silence sec     : {SILENCE_SEC}s", flush=True)
#     print(f"[MAIN] Post-TTS wait   : {POST_TTS_COOLDOWN}s", flush=True)
#     print(f"[MAIN] Persona         : {SYSTEM_PROMPT[:80]}...", flush=True)
#     print("", flush=True)

#     mute_flag = threading.Event()

#     agent = InterviewerAgent(
#         openai_api_key=OPENAI_API_KEY,
#         cartesia_api_key=CARTESIA_API_KEY,
#         system_prompt=SYSTEM_PROMPT,
#         tts_device_index=TTS_DEVICE_INDEX,
#         cartesia_voice_id=CARTESIA_VOICE_ID,
#         mute_flag=mute_flag,
#         post_tts_cooldown=POST_TTS_COOLDOWN,
#     )

#     joined_event = asyncio.Event()
#     meet_task    = asyncio.create_task(run_meet(joined_event))

#     print("[MAIN] Waiting for bot to join meeting...", flush=True)
#     await joined_event.wait()
#     print("[MAIN] ✅ Bot is in the meeting. Starting STT...", flush=True)

#     await asyncio.sleep(3)
#     print("[MAIN] 👋 Triggering opening greeting...", flush=True)
#     threading.Thread(target=agent.greet, daemon=True).start()

#     stt_task = asyncio.create_task(run_stt(agent, mute_flag))

#     done, pending = await asyncio.wait(
#         [meet_task, stt_task],
#         return_when=asyncio.FIRST_COMPLETED
#     )

#     for task in pending:
#         task.cancel()
#         try:
#             await task
#         except asyncio.CancelledError:
#             pass

#     print("[MAIN] All tasks finished. Exiting.", flush=True)


# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         print("\n[MAIN] 👋 Ctrl+C received. Exiting.", flush=True)





















































# #!/usr/bin/env python3
# """
# main.py — Single entry point.
# Pipeline: Join Meet → Greeting → STT (OpenAI Whisper-1) → LLM (GPT-4o-mini) → TTS (Cartesia sonic-3)
# """

# import asyncio
# import os
# import sys
# import threading

# from dotenv import load_dotenv

# from join_meet import run_meet
# from llm_tts import InterviewerAgent
# from stt import run_stt

# load_dotenv()

# # ── Config ────────────────────────────────────────────────────────────────────
# OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
# CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY")
# CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "694f9389-aac1-45b6-b726-9d9369183238")
# STT_DEVICE_INDEX  = int(os.getenv("STT_DEVICE_INDEX", "0"))
# TTS_DEVICE_INDEX  = int(os.getenv("TTS_DEVICE_INDEX", "0"))
# POST_TTS_COOLDOWN = float(os.getenv("POST_TTS_COOLDOWN", "1.0"))
# RMS_THRESHOLD     = float(os.getenv("STT_RMS_THRESHOLD", "0.02"))
# SILENCE_SEC       = float(os.getenv("STT_SILENCE_SEC", "1.5"))

# SYSTEM_PROMPT = os.getenv(
#     "SYSTEM_PROMPT",
#     "You are Alex, a professional AI technical interviewer at INT Technologies. "
#     "Keep your responses concise and conversational."
# )


# async def run_stt_with_restart(agent, mute_flag):
#     """Auto-restarts STT if it crashes. Never cancels the meeting."""
#     retry_delay = 3
#     while True:
#         try:
#             await run_stt(
#                 agent=agent,
#                 mute_flag=mute_flag,
#                 openai_api_key=OPENAI_API_KEY,
#                 device_index=STT_DEVICE_INDEX,
#                 rms_threshold=RMS_THRESHOLD,
#                 silence_sec=SILENCE_SEC,
#             )
#         except asyncio.CancelledError:
#             print("[MAIN] 🛑 STT cancelled.", flush=True)
#             raise
#         except Exception as e:
#             print(f"[MAIN] ⚠️  STT crashed: {e} — restarting in {retry_delay}s...", flush=True)
#             await asyncio.sleep(retry_delay)


# async def main():
#     if not OPENAI_API_KEY:
#         print("❌  OPENAI_API_KEY not set in .env", file=sys.stderr); sys.exit(1)
#     if not CARTESIA_API_KEY:
#         print("❌  CARTESIA_API_KEY not set in .env", file=sys.stderr); sys.exit(1)

#     print("=" * 60, flush=True)
#     print("   🤖 INT Avatar Interview System", flush=True)
#     print("=" * 60, flush=True)
#     print(f"[MAIN] STT   : OpenAI Whisper-1", flush=True)
#     print(f"[MAIN] LLM   : GPT-4o-mini", flush=True)
#     print(f"[MAIN] TTS   : Cartesia sonic-3", flush=True)
#     print(f"[MAIN] RMS threshold : {RMS_THRESHOLD}", flush=True)
#     print(f"[MAIN] Silence sec   : {SILENCE_SEC}s", flush=True)
#     print(f"[MAIN] Post-TTS wait : {POST_TTS_COOLDOWN}s", flush=True)
#     print(f"[MAIN] Persona: {SYSTEM_PROMPT[:80]}...", flush=True)
#     print("", flush=True)

#     mute_flag = threading.Event()

#     agent = InterviewerAgent(
#         openai_api_key=OPENAI_API_KEY,
#         cartesia_api_key=CARTESIA_API_KEY,
#         system_prompt=SYSTEM_PROMPT,
#         tts_device_index=TTS_DEVICE_INDEX,
#         cartesia_voice_id=CARTESIA_VOICE_ID,
#         mute_flag=mute_flag,
#         post_tts_cooldown=POST_TTS_COOLDOWN,
#     )

#     joined_event = asyncio.Event()
#     meet_task = asyncio.create_task(run_meet(joined_event))

#     print("[MAIN] Waiting for bot to join meeting...", flush=True)
#     await joined_event.wait()
#     print("[MAIN] ✅ Bot is in the meeting.", flush=True)

#     await asyncio.sleep(3)
#     print("[MAIN] 👋 Triggering opening greeting...", flush=True)
#     threading.Thread(target=agent.greet, daemon=True).start()

#     stt_task = asyncio.create_task(run_stt_with_restart(agent, mute_flag))

#     # Wait for meeting to end (only when /stop is called from UI)
#     try:
#         await meet_task
#     except asyncio.CancelledError:
#         print("[MAIN] 🛑 Meeting cancelled.", flush=True)
#     except Exception as e:
#         print(f"[MAIN] ❌ Meeting error: {e}", flush=True)
#     finally:
#         print("[MAIN] Stopping STT...", flush=True)
#         stt_task.cancel()
#         try:
#             await stt_task
#         except asyncio.CancelledError:
#             pass

#     print("[MAIN] All tasks finished. Exiting.", flush=True)


# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         print("\n[MAIN] 👋 Ctrl+C received. Exiting.", flush=True)



















































#!/usr/bin/env python3
"""
main.py — Single entry point.
Pipeline: Join Meet → Greeting → GPT Realtime (STT+LLM) → TTS (Cartesia sonic-3)
"""

import asyncio
import os
import sys
import threading

from dotenv import load_dotenv

from join_meet import run_meet
from llm_tts import InterviewerAgent
from realtime import run_realtime

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "694f9389-aac1-45b6-b726-9d9369183238")
STT_DEVICE_INDEX  = int(os.getenv("STT_DEVICE_INDEX", "0"))
TTS_DEVICE_INDEX  = int(os.getenv("TTS_DEVICE_INDEX", "0"))
POST_TTS_COOLDOWN = float(os.getenv("POST_TTS_COOLDOWN", "1.0"))
SILENCE_DURATION  = int(os.getenv("SILENCE_DURATION_MS", "700"))
VOICE_THRESHOLD   = float(os.getenv("VOICE_THRESHOLD", "0.05"))   # ← NEW

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are Alex, a professional AI technical interviewer at INT Technologies. "
    "Keep your responses concise and conversational. Maximum 2-3 sentences per reply."
)


async def run_realtime_with_restart(agent, mute_flag):
    """Auto-restarts GPT Realtime if it crashes. Never cancels the meeting."""
    retry_delay = 3
    while True:
        try:
            await run_realtime(
                agent=agent,
                mute_flag=mute_flag,
                openai_api_key=OPENAI_API_KEY,
                system_prompt=SYSTEM_PROMPT,
                device_index=STT_DEVICE_INDEX,
                silence_duration_ms=SILENCE_DURATION,
                voice_threshold=VOICE_THRESHOLD,       # ← NEW
            )
        except asyncio.CancelledError:
            print("[MAIN] 🛑 Realtime cancelled.", flush=True)
            raise
        except Exception as e:
            print(f"[MAIN] ⚠️  Realtime crashed: {e} — restarting in {retry_delay}s...", flush=True)
            await asyncio.sleep(retry_delay)


async def main():
    if not OPENAI_API_KEY:
        print("❌  OPENAI_API_KEY not set in .env", file=sys.stderr); sys.exit(1)
    if not CARTESIA_API_KEY:
        print("❌  CARTESIA_API_KEY not set in .env", file=sys.stderr); sys.exit(1)

    print("=" * 60, flush=True)
    print("   🤖 INT Avatar Interview System", flush=True)
    print("=" * 60, flush=True)
    print(f"[MAIN] STT + LLM    : GPT Realtime (gpt-4o-realtime-preview)", flush=True)
    print(f"[MAIN] TTS          : Cartesia sonic-3", flush=True)
    print(f"[MAIN] Silence ms   : {SILENCE_DURATION}ms", flush=True)
    print(f"[MAIN] Voice thresh : {VOICE_THRESHOLD} (RMS)", flush=True)               # ← NEW
    print(f"[MAIN] Post-TTS     : {POST_TTS_COOLDOWN}s", flush=True)
    print(f"[MAIN] Barge-in     : ✅ Enabled", flush=True)
    print(f"[MAIN] Persona      : {SYSTEM_PROMPT[:80]}...", flush=True)
    print("", flush=True)

    mute_flag = threading.Event()

    agent = InterviewerAgent(
        openai_api_key=OPENAI_API_KEY,
        cartesia_api_key=CARTESIA_API_KEY,
        system_prompt=SYSTEM_PROMPT,
        tts_device_index=TTS_DEVICE_INDEX,
        cartesia_voice_id=CARTESIA_VOICE_ID,
        mute_flag=mute_flag,
        post_tts_cooldown=POST_TTS_COOLDOWN,
    )

    joined_event = asyncio.Event()
    meet_task = asyncio.create_task(run_meet(joined_event))

    print("[MAIN] Waiting for bot to join meeting...", flush=True)
    await joined_event.wait()
    print("[MAIN] ✅ Bot is in the meeting.", flush=True)

    await asyncio.sleep(3)
    print("[MAIN] 👋 Triggering opening greeting...", flush=True)
    threading.Thread(target=agent.greet, daemon=True).start()

    realtime_task = asyncio.create_task(
        run_realtime_with_restart(agent, mute_flag)
    )

    try:
        await meet_task
    except asyncio.CancelledError:
        print("[MAIN] 🛑 Meeting cancelled.", flush=True)
    except Exception as e:
        print(f"[MAIN] ❌ Meeting error: {e}", flush=True)
    finally:
        print("[MAIN] Stopping Realtime...", flush=True)
        realtime_task.cancel()
        try:
            await realtime_task
        except asyncio.CancelledError:
            pass

    print("[MAIN] All tasks finished. Exiting.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MAIN] 👋 Ctrl+C received. Exiting.", flush=True)
#!/usr/bin/env python3
"""
main.py — Per-session entry point (v5)

KEY CHANGE IN v5: capture_event wired between realtime and vision worker.

New asyncio.Event `capture_event` is created here and passed to both:
  - run_realtime() — sets it on input_audio_buffer.speech_stopped
  - vision_worker.run() — wakes on it, immediately captures screen

This enables on-demand vision capture synchronized with the candidate's
speech, so the screen context is always fresh when GPT generates a response.

Also wires up POST_TTS_COOLDOWN from env (reduced to 0.5s for snappier turns).
"""

import asyncio
import os
import shutil
import subprocess
import sys
import threading

from dotenv import load_dotenv

from join_meet import run_meet
from llm_tts import InterviewerAgent
from realtime import run_realtime
from vision_worker import VisionWorker
from make_prompt import build_greeting_prompt

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SESSION_ID        = os.getenv("SESSION_ID", "default")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "694f9389-aac1-45b6-b726-9d9369183238")
STT_DEVICE_INDEX  = int(os.getenv("STT_DEVICE_INDEX", "0"))
TTS_DEVICE_INDEX  = int(os.getenv("TTS_DEVICE_INDEX", "0"))
POST_TTS_COOLDOWN = float(os.getenv("POST_TTS_COOLDOWN", "0.5"))
SILENCE_DURATION  = int(os.getenv("SILENCE_DURATION_MS", "700"))
VOICE_THRESHOLD   = float(os.getenv("VOICE_THRESHOLD", "0.05"))

PULSE_MIC_SINK   = os.getenv("PULSE_MIC_SINK",   "VirtualMic")
PULSE_SPK_SINK   = os.getenv("PULSE_SPK_SINK",   "VirtualSpeaker")
PULSE_MIC_SOURCE = os.getenv("PULSE_MIC_SOURCE", "VirtualMicSource")

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are Alex, a professional AI technical interviewer at INT Technologies. "
    "Keep your responses concise and conversational. Maximum 2-3 sentences per reply."
)

INTERVIEWER_NAME = os.getenv("INTERVIEWER_NAME", "Alex")
TARGET_ROLE      = os.getenv("TARGET_ROLE",      "Software Engineer")
INTERVIEW_TYPE   = os.getenv("INTERVIEW_TYPE",   "Technical")
TONE             = os.getenv("TONE",             "Professional")

SID8             = SESSION_ID.replace("-", "")[:8]
BASE_PROFILE     = "/tmp/chrome-profile"
BACKUP_PROFILE   = "/tmp/chrome-profile-backup"
SESSION_PROFILE  = os.getenv("CHROME_USER_DATA_DIR", f"/tmp/chrome-profile-{SESSION_ID}")

CHROME_LOCK_FILES = ["SingletonLock", "SingletonCookie", "SingletonSocket"]


# ── Chrome profile setup ──────────────────────────────────────────────────────

def prepare_session_profile() -> str:
    print(f"[{SID8}][PROFILE] Preparing session Chrome profile...", flush=True)
    print(f"[{SID8}][PROFILE]   Base    : {BASE_PROFILE}", flush=True)
    print(f"[{SID8}][PROFILE]   Session : {SESSION_PROFILE}", flush=True)

    source = None
    if os.path.exists(BASE_PROFILE) and os.path.isdir(BASE_PROFILE):
        source = BASE_PROFILE
    elif os.path.exists(BACKUP_PROFILE) and os.path.isdir(BACKUP_PROFILE):
        print(f"[{SID8}][PROFILE] ⚠️  Base missing — using backup.", flush=True)
        source = BACKUP_PROFILE
    else:
        print(f"[{SID8}][PROFILE] ❌ No base profile found.", flush=True)
        print(f"[{SID8}][PROFILE]    Run: docker exec -it int-avatar-bot python /app/setup_login.py", flush=True)
        return SESSION_PROFILE

    if os.path.exists(SESSION_PROFILE):
        shutil.rmtree(SESSION_PROFILE, ignore_errors=True)

    try:
        shutil.copytree(source, SESSION_PROFILE)
        print(f"[{SID8}][PROFILE] ✅ Profile copied.", flush=True)
    except Exception as e:
        print(f"[{SID8}][PROFILE] ⚠️  Copy failed: {e}", flush=True)
        return SESSION_PROFILE

    removed = []
    for lock_file in CHROME_LOCK_FILES:
        lock_path = os.path.join(SESSION_PROFILE, lock_file)
        if os.path.exists(lock_path) or os.path.islink(lock_path):
            try:
                os.remove(lock_path)
                removed.append(lock_file)
            except Exception as e:
                print(f"[{SID8}][PROFILE] ⚠️  Could not remove {lock_file}: {e}", flush=True)

    if removed:
        print(f"[{SID8}][PROFILE] 🔓 Removed Chrome lock files: {', '.join(removed)}", flush=True)
    else:
        print(f"[{SID8}][PROFILE] ✅ No lock files found (clean profile).", flush=True)

    return SESSION_PROFILE


# ── PulseAudio per-session sinks ──────────────────────────────────────────────

def _pactl(*args) -> bool:
    try:
        result = subprocess.run(
            ["pactl"] + list(args), capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[{SID8}][AUDIO] pactl error: {e}", flush=True)
        return False


def create_session_sinks() -> bool:
    print(f"[{SID8}][AUDIO] Creating per-session PulseAudio sinks...", flush=True)
    ok = True
    ok &= _pactl("load-module", "module-null-sink",
                 f"sink_name={PULSE_MIC_SINK}",
                 f"sink_properties=device.description={PULSE_MIC_SINK}")
    ok &= _pactl("load-module", "module-null-sink",
                 f"sink_name={PULSE_SPK_SINK}",
                 f"sink_properties=device.description={PULSE_SPK_SINK}")
    ok &= _pactl("load-module", "module-virtual-source",
                 f"source_name={PULSE_MIC_SOURCE}",
                 f"master={PULSE_MIC_SINK}.monitor")
    if ok:
        print(f"[{SID8}][AUDIO] ✅ Sinks ready:", flush=True)
        print(f"[{SID8}][AUDIO]   TTS   → {PULSE_MIC_SINK} → Chrome mic → Meet", flush=True)
        print(f"[{SID8}][AUDIO]   STT   ← {PULSE_SPK_SINK}.monitor ← Chrome speaker", flush=True)
        print(f"[{SID8}][AUDIO]   Src   : {PULSE_MIC_SOURCE}", flush=True)
    else:
        print(f"[{SID8}][AUDIO] ⚠️  Some sinks may already exist — continuing.", flush=True)
    return ok


def destroy_session_sinks():
    print(f"[{SID8}][AUDIO] Cleaning up PulseAudio sinks...", flush=True)
    try:
        result = subprocess.run(
            ["pactl", "list", "modules", "short"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 1:
                module_index = parts[0]
                line_str = " ".join(parts)
                if (PULSE_MIC_SINK in line_str or
                        PULSE_SPK_SINK in line_str or
                        PULSE_MIC_SOURCE in line_str):
                    _pactl("unload-module", module_index)
                    print(f"[{SID8}][AUDIO] Unloaded module {module_index}", flush=True)
    except Exception as e:
        print(f"[{SID8}][AUDIO] Cleanup warning: {e}", flush=True)


# ── Realtime with auto-restart ────────────────────────────────────────────────

async def run_realtime_with_restart(agent, mute_flag, capture_event):
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
                voice_threshold=VOICE_THRESHOLD,
                session_id=SESSION_ID,
                capture_event=capture_event,    # ← NEW: wired to vision worker
            )
        except asyncio.CancelledError:
            print(f"[{SID8}] 🛑 Realtime cancelled.", flush=True)
            raise
        except Exception as e:
            print(f"[{SID8}] ⚠️  Realtime crashed: {e} — restarting in {retry_delay}s...", flush=True)
            await asyncio.sleep(retry_delay)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    if not OPENAI_API_KEY:
        print(f"[{SID8}] ❌ OPENAI_API_KEY not set", file=sys.stderr); sys.exit(1)
    if not CARTESIA_API_KEY:
        print(f"[{SID8}] ❌ CARTESIA_API_KEY not set", file=sys.stderr); sys.exit(1)

    print("=" * 60, flush=True)
    print(f"   🤖 INT Interview Session [{SID8}]", flush=True)
    print("=" * 60, flush=True)
    print(f"[{SID8}] STT + LLM    : GPT Realtime (gpt-4o-mini-realtime-preview)", flush=True)
    print(f"[{SID8}] TTS          : Cartesia sonic-3", flush=True)
    print(f"[{SID8}] Noise Reduce : near_field (built-in Realtime API)", flush=True)
    print(f"[{SID8}] Barge-in RMS : 0.10 (raised from 0.04 for noisy environments)", flush=True)
    print(f"[{SID8}] Silence ms   : {SILENCE_DURATION}ms", flush=True)
    print(f"[{SID8}] Voice thresh : {VOICE_THRESHOLD} (RMS)", flush=True)
    print(f"[{SID8}] Post-TTS     : {POST_TTS_COOLDOWN}s", flush=True)
    print(f"[{SID8}] Mic sink     : {PULSE_MIC_SINK}", flush=True)
    print(f"[{SID8}] Spk sink     : {PULSE_SPK_SINK}", flush=True)
    print(f"[{SID8}] Mic source   : {PULSE_MIC_SOURCE}", flush=True)
    print(f"[{SID8}] Chrome prof  : {SESSION_PROFILE}", flush=True)
    print(f"[{SID8}] Interviewer  : {INTERVIEWER_NAME} | {INTERVIEW_TYPE} | {TARGET_ROLE}", flush=True)
    print(f"[{SID8}] Vision       : smart activation + on-demand on speech_stopped", flush=True)
    print("", flush=True)

    prepare_session_profile()
    create_session_sinks()

    mute_flag = threading.Event()

    greeting_prompt = build_greeting_prompt(
        interviewer_name = INTERVIEWER_NAME,
        target_role      = TARGET_ROLE,
        interview_type   = INTERVIEW_TYPE,
        tone             = TONE,
    )
    print(f"[{SID8}] Greeting prompt built for: {INTERVIEWER_NAME}", flush=True)

    agent = InterviewerAgent(
        openai_api_key    = OPENAI_API_KEY,
        cartesia_api_key  = CARTESIA_API_KEY,
        system_prompt     = SYSTEM_PROMPT,
        greeting_prompt   = greeting_prompt,
        tts_device_index  = TTS_DEVICE_INDEX,
        cartesia_voice_id = CARTESIA_VOICE_ID,
        mute_flag         = mute_flag,
        post_tts_cooldown = POST_TTS_COOLDOWN,
        pulse_sink        = PULSE_MIC_SINK,
    )

    # ── NEW: shared capture_event between realtime and vision ─────────────────
    # realtime.py sets this on speech_stopped → vision_worker captures immediately
    capture_event = asyncio.Event()

    page_holder       = []
    vision_stop_event = asyncio.Event()
    vision_task       = None

    joined_event = asyncio.Event()
    meet_task = asyncio.create_task(
        run_meet(joined_event, page_holder=page_holder)
    )

    print(f"[{SID8}] Waiting for bot to join meeting...", flush=True)
    await joined_event.wait()
    print(f"[{SID8}] ✅ Bot is in the meeting.", flush=True)

    await asyncio.sleep(0.2)

    if page_holder:
        vision_worker = VisionWorker(
            session_id     = SESSION_ID,
            openai_api_key = OPENAI_API_KEY,
        )
        vision_task = asyncio.create_task(
            vision_worker.run(
                page_holder[0],
                vision_stop_event,
                capture_event=capture_event,    # ← pass capture_event to vision worker
            )
        )
        print(f"[{SID8}] 👁  Vision worker started (smart + on-demand).", flush=True)
    else:
        print(f"[{SID8}] ⚠️  page_holder empty — vision worker not started.", flush=True)

    await asyncio.sleep(3)
    print(f"[{SID8}] 👋 Triggering opening greeting...", flush=True)
    threading.Thread(target=agent.greet, daemon=True).start()

    realtime_task = asyncio.create_task(
        run_realtime_with_restart(agent, mute_flag, capture_event)
    )

    try:
        await meet_task
    except asyncio.CancelledError:
        print(f"[{SID8}] 🛑 Meeting cancelled.", flush=True)
    except Exception as e:
        print(f"[{SID8}] ❌ Meeting error: {e}", flush=True)
    finally:
        print(f"[{SID8}] Stopping Realtime...", flush=True)
        realtime_task.cancel()
        try:
            await realtime_task
        except asyncio.CancelledError:
            pass

        if vision_task and not vision_task.done():
            print(f"[{SID8}] 👁  Stopping vision worker...", flush=True)
            vision_stop_event.set()
            vision_task.cancel()
            try:
                await asyncio.wait_for(vision_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        destroy_session_sinks()

    print(f"[{SID8}] Session finished. Exiting.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{SID8}] 👋 Ctrl+C received. Exiting.", flush=True)
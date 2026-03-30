#!/usr/bin/env python3
"""
api.py — FastAPI backend for INT Interview Bot (Multi-Session)

Each call to /start creates a fully isolated session:
  - Unique session_id (UUID)
  - Isolated Chrome profile: /tmp/chrome-profile-{session_id}
  - Isolated PulseAudio sinks: VMic_{sid8}, VSpk_{sid8}, VMicSrc_{sid8}
  - Isolated subprocess running main.py

Multiple sessions can run simultaneously without interfering.

Endpoints:
  POST /create-meeting            → create Google Meet (bot = host)
  POST /start                     → start a bot session, returns session_id
  GET  /status/{session_id}       → status of a specific session
  POST /stop/{session_id}         → stop a specific session
  GET  /sessions                  → list all active sessions
  POST /generate-prompt           → generate interview persona via GPT
  GET  /health                    → health check
"""

import os
import subprocess
import sys
import threading
import uuid
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from make_prompt import generate_interview_prompt
from meet_creator import create_meet_link

app = FastAPI(title="INT Interview Bot API — Multi-Session")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session store ─────────────────────────────────────────────────────────────
# key: session_id (str UUID)
# value: dict with process, metadata, start time
active_sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


# ── Request / Response Models ─────────────────────────────────────────────────

class StartRequest(BaseModel):
    meetLink: str
    persona: str


class StartResponse(BaseModel):
    session_id: str
    status: str
    meetLink: str


class SessionStatus(BaseModel):
    session_id: str
    status: str       # "running" | "idle" | "not_found"
    meetLink: str = ""
    started_at: float = 0.0


class GeneratePromptRequest(BaseModel):
    interviewer_name: str = "Alex"
    interview_type: str = "Technical"
    target_role: str
    experience_level: str = "1-3 years"
    key_topics: str = ""
    tone: str = "Professional"
    duration_minutes: int = 30


class CreateMeetingRequest(BaseModel):
    title: str = "INT AI Interview Session"
    duration_minutes: int = 60
    candidate_email: Optional[str] = None


class CreateMeetingResponse(BaseModel):
    meet_link: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short_id(session_id: str) -> str:
    """First 8 chars of UUID, no hyphens. Used for PulseAudio sink names."""
    return session_id.replace("-", "")[:8]


def _stream_output(proc: subprocess.Popen, session_id: str):
    """Forward subprocess stdout to Docker logs, prefixed with session id."""
    sid8 = _short_id(session_id)
    try:
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            print(f"[{sid8}] {text}", flush=True)
    except Exception:
        pass


def _reap_dead_sessions():
    """Background thread — removes sessions whose subprocess has exited."""
    while True:
        time.sleep(10)
        with sessions_lock:
            dead = [
                sid for sid, info in active_sessions.items()
                if info["process"].poll() is not None
            ]
            for sid in dead:
                print(f"[API] 🧹 Session {_short_id(sid)} ended — removing.", flush=True)
                del active_sessions[sid]


# Start reaper thread
threading.Thread(target=_reap_dead_sessions, daemon=True).start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/create-meeting", response_model=CreateMeetingResponse)
async def create_meeting(req: CreateMeetingRequest):
    """
    Creates a Google Meet via Calendar API. Bot's account = host.
    No Quick Access restrictions. Works for every interview.
    """
    try:
        valid_email = req.candidate_email.strip() if req.candidate_email and req.candidate_email.strip() else None
        print(f"[API] 📅 Creating Meet: '{req.title}' ({req.duration_minutes} min)", flush=True)
        meet_link = create_meet_link(
            title=req.title,
            duration_minutes=req.duration_minutes,
            candidate_email=valid_email,
        )
        print(f"[API] ✅ Meet link: {meet_link}", flush=True)
        return CreateMeetingResponse(meet_link=meet_link)

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"token.json missing: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Meet: {e}")


@app.post("/generate-prompt")
async def generate_prompt(req: GeneratePromptRequest):
    persona = generate_interview_prompt(
        interviewer_name=req.interviewer_name,
        interview_type=req.interview_type,
        target_role=req.target_role,
        experience_level=req.experience_level,
        key_topics=req.key_topics,
        tone=req.tone,
        duration_minutes=req.duration_minutes,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    print(f"[API] 📝 Prompt generated for: {req.target_role}", flush=True)
    return {"persona": persona}


@app.post("/start", response_model=StartResponse)
async def start_bot(req: StartRequest):
    """
    Starts a new isolated bot session.
    Returns a session_id that the frontend uses for all subsequent calls.
    """
    session_id = str(uuid.uuid4())
    sid8 = _short_id(session_id)

    # Per-session isolated Chrome profile
    chrome_profile = f"/tmp/chrome-profile-{session_id}"

    # Per-session PulseAudio sink names
    mic_sink    = f"VMic_{sid8}"       # TTS plays here → Chrome mic → Meet
    spk_sink    = f"VSpk_{sid8}"       # Chrome speaker output → STT listens here
    mic_source  = f"VMicSrc_{sid8}"    # Virtual source from mic_sink.monitor

    env = os.environ.copy()
    env["SESSION_ID"]           = session_id
    env["MEETING_LINK"]         = req.meetLink
    env["SYSTEM_PROMPT"]        = req.persona
    env["CHROME_USER_DATA_DIR"] = chrome_profile
    env["PULSE_MIC_SINK"]       = mic_sink
    env["PULSE_SPK_SINK"]       = spk_sink
    env["PULSE_MIC_SOURCE"]     = mic_source
    # Override default PulseAudio routing for this process tree
    env["PULSE_SINK"]           = mic_sink
    env["PULSE_SOURCE"]         = mic_source

    proc = subprocess.Popen(
        [sys.executable, "/app/main.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Stream logs tagged with session short-id
    t = threading.Thread(target=_stream_output, args=(proc, session_id), daemon=True)
    t.start()

    with sessions_lock:
        active_sessions[session_id] = {
            "process":    proc,
            "meetLink":   req.meetLink,
            "persona":    req.persona[:60],
            "started_at": time.time(),
            "chrome_profile": chrome_profile,
            "mic_sink":   mic_sink,
            "spk_sink":   spk_sink,
            "mic_source": mic_source,
        }

    print(f"[API] ✅ Session started: {sid8} (PID {proc.pid})", flush=True)
    print(f"[API]    Meet   : {req.meetLink}", flush=True)
    print(f"[API]    Sinks  : {mic_sink} / {spk_sink} / {mic_source}", flush=True)
    print(f"[API]    Profile: {chrome_profile}", flush=True)

    return StartResponse(session_id=session_id, status="launching", meetLink=req.meetLink)


@app.get("/status/{session_id}", response_model=SessionStatus)
async def get_status(session_id: str):
    with sessions_lock:
        info = active_sessions.get(session_id)

    if not info:
        return SessionStatus(session_id=session_id, status="not_found")

    if info["process"].poll() is None:
        return SessionStatus(
            session_id=session_id,
            status="running",
            meetLink=info["meetLink"],
            started_at=info["started_at"],
        )

    # Process has exited — clean up
    with sessions_lock:
        active_sessions.pop(session_id, None)

    return SessionStatus(session_id=session_id, status="idle")


@app.post("/stop/{session_id}")
async def stop_bot(session_id: str):
    with sessions_lock:
        info = active_sessions.get(session_id)

    if not info:
        return {"status": "not_found", "session_id": session_id}

    proc = info["process"]
    sid8 = _short_id(session_id)

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    with sessions_lock:
        active_sessions.pop(session_id, None)

    print(f"[API] 🛑 Session stopped: {sid8}", flush=True)
    return {"status": "stopped", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    """Lists all currently active sessions. Useful for monitoring."""
    with sessions_lock:
        result = []
        for sid, info in active_sessions.items():
            running = info["process"].poll() is None
            result.append({
                "session_id":  sid,
                "short_id":    _short_id(sid),
                "status":      "running" if running else "idle",
                "meetLink":    info["meetLink"],
                "started_at":  info["started_at"],
                "uptime_sec":  int(time.time() - info["started_at"]),
            })
    return {"sessions": result, "count": len(result)}


@app.get("/health")
async def health():
    with sessions_lock:
        count = len(active_sessions)
    return {"ok": True, "active_sessions": count}
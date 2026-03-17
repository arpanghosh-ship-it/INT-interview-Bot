# #!/usr/bin/env python3
# """
# api.py — FastAPI backend for INT Interview Bot
# Endpoints:
#   POST /start   → receives meetLink + persona, starts the bot
#   GET  /status  → returns running/idle
#   POST /stop    → kills the bot
# """

# import asyncio
# import os
# import signal
# import subprocess
# import sys
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel

# app = FastAPI(title="INT Interview Bot API")

# # Allow requests from any origin (your Loveable frontend on EC2 port 80)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Global bot process reference
# bot_process: subprocess.Popen | None = None


# class StartRequest(BaseModel):
#     meetLink: str   # matches frontend field name exactly
#     persona: str


# class StatusResponse(BaseModel):
#     status: str     # "running" | "idle"
#     meetLink: str = ""
#     persona: str = ""


# # Store current session info
# current_session = {"meetLink": "", "persona": ""}


# @app.post("/start")
# async def start_bot(req: StartRequest):
#     global bot_process, current_session

#     # Kill existing bot if running
#     if bot_process and bot_process.poll() is None:
#         bot_process.terminate()
#         try:
#             bot_process.wait(timeout=5)
#         except subprocess.TimeoutExpired:
#             bot_process.kill()
#         bot_process = None

#     # Set env vars for this session
#     env = os.environ.copy()
#     env["MEETING_LINK"]  = req.meetLink
#     env["SYSTEM_PROMPT"] = req.persona

#     # Spawn main.py as a subprocess
#     bot_process = subprocess.Popen(
#         [sys.executable, "/app/main.py"],
#         env=env,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.STDOUT,
#     )

#     current_session = {"meetLink": req.meetLink, "persona": req.persona}
#     print(f"[API] ✅ Bot started (PID {bot_process.pid})", flush=True)
#     print(f"[API]    Meet : {req.meetLink}", flush=True)
#     print(f"[API]    Persona: {req.persona[:60]}...", flush=True)

#     return {"status": "launching", "pid": bot_process.pid}


# @app.get("/status")
# async def get_status():
#     global bot_process
#     if bot_process and bot_process.poll() is None:
#         return StatusResponse(
#             status="running",
#             meetLink=current_session["meetLink"],
#             persona=current_session["persona"],
#         )
#     return StatusResponse(status="idle")


# @app.post("/stop")
# async def stop_bot():
#     global bot_process, current_session

#     if bot_process and bot_process.poll() is None:
#         pid = bot_process.pid
#         bot_process.terminate()
#         try:
#             bot_process.wait(timeout=8)
#         except subprocess.TimeoutExpired:
#             bot_process.kill()
#         bot_process = None
#         current_session = {"meetLink": "", "persona": ""}
#         print(f"[API] 🛑 Bot stopped (was PID {pid})", flush=True)
#         return {"status": "stopped"}

#     return {"status": "already_idle"}


# @app.get("/health")
# async def health():
#     return {"ok": True}










#!/usr/bin/env python3
"""
api.py — FastAPI backend for INT Interview Bot
Endpoints:
  POST /start   → receives meetLink + persona, starts the bot
  GET  /status  → returns running/idle
  POST /stop    → kills the bot
"""

import os
import subprocess
import sys
import threading                    # ← ADDED

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="INT Interview Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_process: subprocess.Popen | None = None
current_session = {"meetLink": "", "persona": ""}


class StartRequest(BaseModel):
    meetLink: str
    persona: str


class StatusResponse(BaseModel):
    status: str
    meetLink: str = ""
    persona: str = ""


# ── ADDED: Forward main.py output to Docker logs in real time ─────────────────
def _stream_output(proc: subprocess.Popen):
    """
    Reads main.py subprocess stdout line by line and prints to Docker logs.
    Without this, ALL print() from main.py are silently swallowed.
    Runs in a daemon thread — dies automatically when container stops.
    """
    try:
        for line in iter(proc.stdout.readline, b""):
            print(line.decode("utf-8", errors="replace"), end="", flush=True)
    except Exception:
        pass


@app.post("/start")
async def start_bot(req: StartRequest):
    global bot_process, current_session

    # Kill existing bot if running
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()
        bot_process = None

    env = os.environ.copy()
    env["MEETING_LINK"]  = req.meetLink
    env["SYSTEM_PROMPT"] = req.persona

    bot_process = subprocess.Popen(
        [sys.executable, "/app/main.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # ── ADDED: Start output forwarding thread ─────────────────────────────────
    t = threading.Thread(target=_stream_output, args=(bot_process,), daemon=True)
    t.start()

    current_session = {"meetLink": req.meetLink, "persona": req.persona}
    print(f"[API] ✅ Bot started (PID {bot_process.pid})", flush=True)
    print(f"[API]    Meet    : {req.meetLink}", flush=True)
    print(f"[API]    Persona : {req.persona[:60]}...", flush=True)

    return {"status": "launching", "pid": bot_process.pid}


@app.get("/status")
async def get_status():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return StatusResponse(
            status="running",
            meetLink=current_session["meetLink"],
            persona=current_session["persona"],
        )
    return StatusResponse(status="idle")


@app.post("/stop")
async def stop_bot():
    global bot_process, current_session

    if bot_process and bot_process.poll() is None:
        pid = bot_process.pid
        bot_process.terminate()
        try:
            bot_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            bot_process.kill()
        bot_process = None
        current_session = {"meetLink": "", "persona": ""}
        print(f"[API] 🛑 Bot stopped (was PID {pid})", flush=True)
        return {"status": "stopped"}

    return {"status": "already_idle"}


@app.get("/health")
async def health():
    return {"ok": True}
# 🤖 INT Avatar Interview Bot

An AI-powered interview bot that joins Google Meet as host, conducts real-time voice interviews, and sees the candidate's screen share — all with human-like conversational latency.

---

## 🧠 How It Works

```
Candidate speaks in Meet
        ↓
Chrome captures audio → VSpk_{sid} (PulseAudio, per-session)
        ↓
GPT Realtime API (STT + LLM combined, semantic VAD)
        ↓
Cartesia Sonic-3 TTS → paplay → VMic_{sid} → Chrome mic → Meet
        ↓
Candidate hears Alex respond in ~0.8–1.5s

[In parallel — Vision Pipeline]
Playwright page.screenshot() every 1s
        ↓
Perceptual hash diff detection (skip unchanged frames)
        ↓
GPT-4o-mini vision → {summary, screen_type, key_entities, confidence}
        ↓
Tier 1: conversation.item.create → [SCREEN EVENT] in LLM history (significant changes)
Tier 2: session.update → background instructions (all changes)
        ↓
Bot can see screen share and answer "Can you see my screen?" correctly
```

---

## ⚡ Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Playwright (Chromium, headless=False) |
| STT + LLM | OpenAI GPT Realtime API (`gpt-4o-mini-realtime-preview`) |
| TTS | Cartesia Sonic-3 (WAV PCM → paplay) |
| VAD | Semantic VAD (fires on sentence completion, not silence) |
| Barge-in | Client RMS threshold + OpenAI `interrupt_response=True` |
| Screen vision | GPT-4o-mini vision, Playwright screenshot, perceptual hash diff |
| Prompt generation | GPT-4o-mini (interview plan) + hardcoded vision + voice rules |
| Meet creation | Google Calendar API (bot = host, no Quick Access) |
| API | FastAPI + Uvicorn |
| Frontend | React + Vite + shadcn/ui |
| Web server | Nginx (reverse proxy) |
| Audio routing | PulseAudio virtual cables inside Docker (per-session isolated) |
| Deployment | Docker + Docker Compose on AWS EC2 |
| Remote access | Cloudflare Tunnel (cloudflared) |

---

## 📁 Project Structure

```
INT-interview-Bot/
├── Backend/
│   ├── api.py              FastAPI — sessions, routing, subprocess management
│   ├── main.py             Per-session orchestrator — Meet + Vision + Realtime
│   ├── join_meet.py        Playwright — signs in, joins Meet, exposes page to vision
│   ├── realtime.py         GPT Realtime WebSocket — STT + LLM + dual-tier vision injection
│   ├── llm_tts.py          Cartesia TTS + barge-in
│   ├── make_prompt.py      Master prompt builder: identity + vision block + voice rules
│   ├── screen_context.py   Per-session vision context store (live events + background)
│   ├── vision_capture.py   Playwright screenshot capture
│   ├── vision_diff.py      Perceptual hash (aHash) frame diff detection
│   ├── vision_worker.py    Async vision worker: capture → diff → analyze → inject
│   ├── meet_creator.py     Google Calendar API Meet link creator
│   ├── setup_login.py      ONE-TIME: Google login setup after docker-compose up
│   ├── get_token.py        ONE-TIME LOCAL: OAuth2 token generator
│   ├── credentials.json    Google OAuth2 client secret
│   ├── token.json          Pre-authorized OAuth2 token
│   ├── requirements.txt    Python dependencies
│   ├── Dockerfile          python:3.11-slim + Chrome + PulseAudio + noVNC
│   └── start.sh            Container startup: Xvfb → noVNC → PulseAudio → FastAPI
├── Frontend/
│   ├── src/pages/Index.tsx   Main UI — form, persona preview, session management
│   └── dist/                 Built output served by Nginx
├── docker-compose.yaml
└── nginx.conf
```

---

## 🔧 Environment Variables

Create `Backend/.env`:

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Cartesia
CARTESIA_API_KEY=sk_car_...
CARTESIA_VOICE_ID=5ee9feff-1265-424a-9d7f-8e4d431a12c7

# Google Calendar API (Meet creation)
GOOGLE_CREDENTIALS_PATH=/app/credentials.json
GOOGLE_TOKEN_PATH=/app/token.json

# Audio tuning
SILENCE_DURATION_MS=700
VOICE_THRESHOLD=0.05
POST_TTS_COOLDOWN=1.0
STT_DEVICE_INDEX=0
TTS_DEVICE_INDEX=0

# Vision pipeline (optional — defaults shown)
VISION_MODEL=gpt-4o-mini
VISION_CAPTURE_INTERVAL=1.0
VISION_DIFF_THRESHOLD=0.05
VISION_MAX_PER_MINUTE=15
VISION_CONTEXT_CHECK_INTERVAL=1.0
```

---

## 🐳 Docker Ports

| Port | Service |
|------|---------|
| 4001 | React frontend (Nginx) |
| 4002 | FastAPI backend API |
| 4003 | noVNC debug viewer (view Chrome inside Docker) |

---

## 🚀 Setup

### Prerequisites
- Docker + Docker Compose
- Node.js 18+

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/INT-interview-Bot.git
cd INT-interview-Bot

# 2. Create .env
cp Backend/.env.example Backend/.env
# Edit with your API keys

# 3. Build frontend
cd Frontend && npm install && npm run build && cd ..

# 4. Start everything
docker compose up --build -d

# 5. One-time Google login (required after every full rebuild)
docker exec -it int-avatar-bot python /app/setup_login.py
# Open http://localhost:4003/vnc.html → log into Google → script exits

# 6. Open the UI
# http://localhost:4001
```

---

## 🌐 EC2 Deployment

```bash
# SSH into server
ssh ubuntu@YOUR_EC2_IP
cd ~/INT-interview-Bot

# Pull latest
git pull

# If requirements.txt changed (e.g. new pip packages):
docker compose down
docker compose build --no-cache
docker compose up -d

# If only backend .py files changed (faster):
docker cp Backend/main.py int-avatar-bot:/app/main.py
docker compose restart backend

# If only frontend changed:
cd Frontend && npm run build && cd ..
# No docker restart needed — Nginx volume-mounts dist/

# After any rebuild:
docker exec -it int-avatar-bot python /app/setup_login.py
```

**AWS Security Group — open these ports:**

| Port | Type |
|------|------|
| 22 | SSH |
| 4001 | Custom TCP |
| 4002 | Custom TCP |
| 4003 | Custom TCP |

---

## 🔊 Audio Architecture

```
TTS FLOW (Alex speaks into Meet):
  llm_tts.py → Cartesia API → WAV bytes → paplay --device=VMic_{sid}
  → VMic_{sid}.monitor → VMicSrc_{sid}
  → Chrome mic → Meet participants hear Alex ✅

STT FLOW (bot hears candidate):
  Candidate speaks → Chrome audio output → VSpk_{sid} sink
  → VSpk_{sid}.monitor
  → sounddevice InputStream @ 44100Hz
  → resample to 24000Hz in Python
  → GPT Realtime WebSocket (STT + LLM) ✅

CRITICAL RULES — DO NOT CHANGE:
  samplerate=44100Hz   — PulseAudio native rate; changing = silence
  headless=False       — headless mode disables Chrome audio
  Default sink = VSpk  — NEVER VMic (causes TTS echo loop)
```

---

## 👁 Vision Architecture

```
CAPTURE (every 1.0s):
  join_meet.py owns the Playwright page
  → page_holder list shares page reference with VisionWorker
  → vision_capture.py: page.screenshot() → PNG bytes

DIFF DETECTION:
  vision_diff.py: perceptual hash (aHash 8×8, 64 bits)
  → Hamming distance / 64 = diff_score
  → diff_score < 0.05 → skip (unchanged screen)
  → diff_score ≥ 0.05 → analyze

ANALYSIS (in thread pool, never blocks event loop):
  vision_worker.py → GPT-4o-mini vision (detail="auto")
  → returns JSON: {summary, screen_type, key_entities, raw_text_excerpt, confidence}
  → screen_types: code | document | slide | browser | video | empty | unknown

CONTEXT INJECTION (realtime.py _update_context(), every 1.0s):
  Tier 1 — Significant change (sharing started/stopped/type changed):
    conversation.item.create → [SCREEN EVENT] goes into LLM conversation history
    Bot can now answer "can you see my screen?" correctly ✅

  Tier 2 — Any new context:
    session.update (instructions only) → background context updated silently
    Persists across all future turns ✅
```

---

## 🤖 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/create-meeting` | Create Google Meet (bot = host) |
| POST | `/generate-prompt` | Generate interview persona via GPT-4o-mini |
| POST | `/start` | Start bot session → returns `session_id` |
| GET | `/status/{session_id}` | Status of a specific session |
| POST | `/stop/{session_id}` | Stop a specific session |
| GET | `/sessions` | List all active sessions |
| GET | `/health` | Health check + active session count |

---

## ⚡ Barge-in (Interruption)

```
realtime.py detects RMS > 0.04 while muted (bot is speaking)
        ↓
agent.interrupt() → paplay.terminate() → Alex stops mid-sentence
        ↓
OpenAI interrupt_response=True cancels pending server response
        ↓
0.2s cooldown → mute_flag clears → GPT Realtime listens again
        ↓
Candidate's new speech captured → new response generated ✅
```

---

## 📋 Master Prompt Structure

Every session prompt is assembled in four mandatory sections:

```
1. Interview Identity + Structure   ← GPT-4o-mini generated (or rule-based fallback)
   - Interviewer name, tone, opening line
   - Interview phases with timing and role-specific questions

2. Screen Vision Capability         ← ALWAYS hardcoded (never GPT-generated)
   - Bot knows it has real-time screen vision
   - Knows how to handle [SCREEN EVENT] messages in conversation history
   - Knows how to answer "can you see my screen?"
   - Screen-type guidance: code / slides / documents / browser

3. Voice Conversation Rules         ← ALWAYS hardcoded (never GPT-generated)
   - Max 2-3 sentences per response
   - One question at a time
   - No hollow filler phrases
   - Barge-in awareness
```

---

## 🛠️ Useful Commands

```bash
# Live logs
docker logs -f int-avatar-bot

# Check active sessions
curl http://YOUR_IP:4002/sessions

# Health check
curl http://YOUR_IP:4002/health

# Debug audio sinks
docker exec int-avatar-bot pactl list sinks short
docker exec int-avatar-bot pactl list sources short

# Verify Pillow (vision diff)
docker exec int-avatar-bot python -c "from PIL import Image; print('Pillow OK')"

# Resource monitoring
docker stats int-avatar-bot

# Stop everything
docker compose down

# Full rebuild
docker compose build --no-cache && docker compose up -d
```

---

## 🌍 Public URL (Cloudflare Tunnel)

```bash
# Expose frontend publicly (Windows)
cloudflared-windows-amd64.exe tunnel --protocol http2 --url http://localhost:4001
# Gets: https://random-words.trycloudflare.com
```

> Note: URL changes on every restart. For a permanent URL, attach a domain in Cloudflare.

---

## 🗺️ Roadmap

- [x] Multi-session voice interview bot
- [x] Google Meet creation as host (no Quick Access issues)
- [x] Barge-in support
- [x] Real-time screen vision (capture → diff → analyze → inject)
- [x] Dual-tier context injection (live conversation events + background)
- [x] Vision-aware master prompt (bot knows it can see the screen)
- [ ] AI Avatar video with lip-sync (HeyGen LiveAvatar Lite or MuseTalk)
- [ ] Session transcripts saved to disk / database
- [ ] Chrome profile persistence across rebuilds (named Docker volume)
- [ ] GPT Realtime quality / VAD tuning per session

---

## ⚠️ Important Notes

- Never commit `Backend/.env` — it contains API keys
- The bot uses a dedicated Google account — do not use your personal account
- `Frontend/dist/` must be built before `docker-compose up`
- noVNC (port 4003) is for debugging only — do not expose publicly
- After every full rebuild, `setup_login.py` must be re-run (Chrome profile is reset)
- Vision uses OpenAI API credits (GPT-4o-mini vision calls) — monitor usage with `VISION_MAX_PER_MINUTE`
- Each session runs Chrome + GPT Realtime WebSocket + VisionWorker — monitor with `docker stats`

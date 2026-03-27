# 🤖 INT Avatar Interview Bot

An AI-powered bot that joins Google Meet, conducts real-time voice interviews, and responds with human-like conversational latency.

---

## 🧠 How It Works

```
Candidate speaks in Meet
        ↓
Chrome captures audio → VirtualSpeaker (PulseAudio)
        ↓
GPT Realtime API (STT + LLM combined, semantic VAD)
        ↓
Cartesia Sonic-3 TTS (streaming → paplay → VirtualMic → Chrome mic → Meet)
        ↓
Candidate hears Alex respond in ~0.8-1.5s
```

---

## ⚡ Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Playwright (Chromium, headless=False) |
| STT + LLM | OpenAI GPT Realtime API (`gpt-4o-mini-realtime-preview`) |
| TTS | Cartesia Sonic-3 (streaming PCM → paplay) |
| VAD | Semantic VAD (fires on sentence completion, not silence) |
| Barge-in | Client RMS + OpenAI `interrupt_response=True` |
| API | FastAPI + Uvicorn |
| Frontend | React + Vite + shadcn/ui |
| Web server | Nginx (reverse proxy) |
| Audio routing | PulseAudio virtual cables inside Docker |
| Deployment | Docker + Docker Compose |
| Public URL | Cloudflare Tunnel (cloudflared) |

---

## 📁 Project Structure

```
InterviewBot/
├── Backend/
│   ├── api.py          FastAPI — /start /stop /status /health
│   ├── main.py         Orchestration entry point
│   ├── join_meet.py    Playwright — signs into Google, joins Meet
│   ├── realtime.py     GPT Realtime WebSocket (STT + LLM combined)
│   ├── llm_tts.py      Cartesia TTS streaming + barge-in logic
│   ├── start.sh        Container startup — Xvfb, PulseAudio, FastAPI
│   ├── Dockerfile      Python 3.11-slim + Playwright + audio libs
│   ├── requirements.txt
│   └── .env            API keys (never commit this)
├── Frontend/
│   ├── src/pages/Index.tsx   UI — meetLink + persona → POST /api/start
│   └── dist/                 Built output served by Nginx
├── docker-compose.yaml
└── nginx.conf
```

---

## 🔧 Environment Variables

Create `Backend/.env` with these values:

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Cartesia
CARTESIA_API_KEY=sk_car_...
CARTESIA_VOICE_ID=5ee9feff-1265-424a-9d7f-8e4d431a12c7

# Google account (used to join Meet)
GOOGLE_EMAIL=your-bot@gmail.com
GOOGLE_PASSWORD=yourpassword

# Bot settings
MEETING_LINK=https://meet.google.com/xxx-xxxx-xxx
STAY_DURATION_SECONDS=7200
STT_DEVICE_INDEX=0
TTS_DEVICE_INDEX=0
POST_TTS_COOLDOWN=0.3
VOICE_THRESHOLD=0.05
SILENCE_DURATION_MS=500
AVATAR_NAME=INT Interview Bot

# Bot persona (shown in UI, overridden dynamically per session)
SYSTEM_PROMPT=You are Alex, a professional HR interviewer at INT Technologies...
```

---

## 🐳 Docker Ports

| Port | Service |
|------|---------|
| 4001 | FastAPI backend API |
| 4002 | noVNC debug viewer (view Chrome inside Docker) |
| 4003 | React frontend (Nginx) |

---

## 🚀 Local Setup

### Prerequisites
- Docker Desktop
- Node.js 18+
- Git

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/AI-interview-bot.git
cd AI-interview-bot

# 2. Create .env
cp Backend/.env.example Backend/.env
# Edit Backend/.env with your API keys

# 3. Build frontend
cd Frontend && npm install && npm run build && cd ..

# 4. Start everything
docker-compose up --build

# 5. Open the UI
# http://localhost:4003
```

---

## 🌐 EC2 Deployment

```bash
# SSH into server
ssh developer@YOUR_SERVER_IP

# Go to project folder
cd ~/InterviewBot

# Clone repo
git clone https://github.com/YOUR_USERNAME/AI-interview-bot.git .

# Create .env
nano Backend/.env

# Build frontend
cd Frontend && npm install && npm run build && cd ..

# Start in background
sudo docker-compose up --build -d

# Watch logs
sudo docker logs int-avatar-bot -f
```

**AWS Security Group — open these ports:**

| Port | Type |
|------|------|
| 22 | SSH |
| 4001 | Custom TCP |
| 4002 | Custom TCP |
| 4003 | Custom TCP |

Access at:
```
http://YOUR_SERVER_IP:4003          ← Live UI
http://YOUR_SERVER_IP:4001/docs     ← FastAPI docs
http://YOUR_SERVER_IP:4002/vnc.html ← noVNC debug viewer
```

---

## 🔊 Audio Architecture

```
TTS FLOW (Alex speaks into Meet):
  llm_tts.py → Cartesia API → raw PCM stream
  → paplay --raw --device=VirtualMic (streaming, no temp file)
  → VirtualMic.monitor → VirtualMicSource
  → Chrome mic → Meet participants hear Alex ✅

STT FLOW (bot hears candidate):
  Candidate speaks → Chrome audio output → VirtualSpeaker sink
  → VirtualSpeaker.monitor
  → sounddevice InputStream @ 44100Hz (MUST be 44100Hz)
  → resample to 24000Hz in Python
  → GPT Realtime WebSocket (STT + LLM in one connection) ✅

CRITICAL RULES — DO NOT CHANGE:
  samplerate=44100Hz   — PulseAudio rate, changing = silence
  headless=False       — headless disables Chrome audio
  paplay --raw         — streaming mode, no WAV header
```

---

## 🤖 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/start` | Start bot `{ meetLink, persona }` |
| GET | `/status` | Check if bot is running |
| POST | `/stop` | Stop the bot |
| GET | `/health` | Health check |

---

## ⚡ Barge-in (Interruption)

When the bot is speaking and the candidate talks over it:

```
realtime.py detects RMS > 0.04 while muted
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

## 🔁 Update & Redeploy

```bash
# Push changes from Windows
git add .
git commit -m "your update"
git push

# On EC2 — pull and restart
ssh developer@YOUR_SERVER_IP
cd ~/InterviewBot
git pull

# If backend changed:
sudo docker-compose build --no-cache backend
sudo docker-compose up -d

# If only frontend changed:
cd Frontend && npm run build && cd ..
sudo docker-compose restart frontend
```

---

## 🛠️ Useful Docker Commands

```bash
# Watch live logs
sudo docker logs int-avatar-bot -f

# Check running containers
sudo docker ps

# Stop everything
sudo docker-compose down

# Full rebuild
sudo docker-compose build --no-cache
sudo docker-compose up -d

# Debug audio inside container
docker exec int-avatar-bot pactl list sinks short
docker exec int-avatar-bot pactl list sources short
```

---

## 🌍 Public URL (Cloudflare Tunnel)

```bash
# Windows — expose frontend publicly
cd Downloads
cloudflared-windows-amd64.exe tunnel --protocol http2 --url http://localhost:4003
# Gets: https://random-words.trycloudflare.com
```

> Note: URL changes on every restart. For a permanent URL, add a domain to Cloudflare.

---

## ⚠️ Important Notes

- Never commit `Backend/.env` — it contains API keys
- The bot uses a dedicated Google account — do not use your personal account
- `Frontend/dist/` must be built before `docker-compose up`
- noVNC (port 4002) is for debugging only — do not expose publicly
- Only one interview session runs at a time — a second `/start` kills the first

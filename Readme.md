# 🤖 INT Avatar Interview Bot

An AI-powered interview bot that joins Google Meet, listens to candidates via Speech-to-Text, generates intelligent responses using GPT-4o-mini, and speaks via Cartesia TTS — all running inside Docker.

---

## 🏗️ Architecture

```
InterviewBot/
├── Backend/              # Python bot + FastAPI server
│   ├── api.py            # FastAPI REST API (POST /start, /stop, GET /status)
│   ├── main.py           # Bot entry point (STT → LLM → TTS pipeline)
│   ├── join_meet.py      # Playwright bot that joins Google Meet
│   ├── llm_tts.py        # GPT-4o-mini + Cartesia TTS
│   ├── start.sh          # Container startup script
│   ├── Dockerfile        # Docker build config
│   ├── requirements.txt  # Python dependencies
│   └── .env              # API keys (never commit this!)
├── Frontend/             # React UI (Loveable + shadcn/ui)
│   ├── src/pages/Index.tsx
│   └── dist/             # Built output (served by Nginx)
├── docker-compose.yaml   # Orchestrates backend + frontend
└── nginx.conf            # Nginx reverse proxy config
```

---

## 🔌 How It Works

```
User fills form (Meet link + Bot Persona)
  → React UI: POST /api/start
  → Nginx proxies to FastAPI (port 8000)
  → FastAPI sets MEETING_LINK + SYSTEM_PROMPT env vars
  → Spawns main.py subprocess
  → Playwright joins Google Meet
  → Whisper STT listens to participants
  → GPT-4o-mini generates responses
  → Cartesia TTS speaks via VirtualMic → Chrome → Meet
```

---

## ⚙️ Environment Variables

Create `Backend/.env` with:

```env
# Google Account (used to join Meet)
GOOGLE_EMAIL=your-bot@gmail.com
GOOGLE_PASSWORD=your-password

# OpenAI (Whisper STT + GPT-4o-mini)
OPENAI_API_KEY=sk-...

# Cartesia TTS
CARTESIA_API_KEY=...
CARTESIA_VOICE_ID=5ee9feff-1265-424a-9d7f-8e4d431a12c7

# Meet settings
MEETING_LINK=https://meet.google.com/xxx-xxxx-xxx
STAY_DURATION_SECONDS=7200

# Bot persona (overridden dynamically by API)
SYSTEM_PROMPT=You are Alex, a professional AI technical interviewer at INT Technologies.
```

---

## 🚀 Local Setup

### Prerequisites
- Docker Desktop
- Node.js 18+
- Git

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/interview-bot.git
cd interview-bot

# 2. Create .env file
cp Backend/.env.example Backend/.env
# Edit Backend/.env with your API keys

# 3. Build React frontend
cd Frontend
npm install
npm run build
cd ..

# 4. Start everything
docker-compose up --build
```

### Access
| URL | Description |
|-----|-------------|
| `http://localhost` | Interview Bot UI |
| `http://localhost:8000/docs` | FastAPI API docs |
| `http://localhost:6080/vnc.html` | Live browser view (debug) |

---

## 🌐 EC2 Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for full server setup guide.

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/start` | Start the bot `{ meetLink, persona }` |
| GET | `/status` | Check if bot is running |
| POST | `/stop` | Stop the bot |
| GET | `/health` | Health check |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + TypeScript + Tailwind + shadcn/ui |
| Backend API | FastAPI + Uvicorn |
| Browser Automation | Playwright (Chromium) |
| Speech-to-Text | OpenAI Whisper |
| LLM | GPT-4o-mini |
| Text-to-Speech | Cartesia Sonic-3 |
| Audio Routing | PulseAudio virtual cables |
| Container | Docker + Docker Compose |
| Web Server | Nginx |

---

## ⚠️ Important Notes

- Never commit `Backend/.env` to GitHub (already in `.gitignore`)
- The bot uses a dedicated Google account — do not use your personal account
- `Frontend/dist/` is built locally and committed, OR built on the server
- noVNC (port 6080) is for debugging only — do not expose publicly
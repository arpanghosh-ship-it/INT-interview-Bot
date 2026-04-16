# 🤖 INT Avatar Interview Bot

An AI-powered bot that joins Google Meet as host, conducts real-time voice interviews, and sees the candidate's screen share in real time — with human-like conversational latency.

---

## 🧠 How It Works

### Voice Pipeline
```
Candidate speaks in Meet
        ↓
Chrome captures audio → VSpk_{sid} (PulseAudio, per-session isolated)
        ↓
GPT Realtime API (STT + LLM combined, semantic VAD)
        ↓
Cartesia Sonic-3 TTS → paplay → VMic_{sid} → Chrome mic → Meet
        ↓
Candidate hears Alex respond in ~0.8–1.5s
```

### Vision Pipeline (runs in parallel — never blocks voice)
```
Playwright page.screenshot() every 1.0s
        ↓
Perceptual hash diff (aHash 8×8) — skip unchanged frames
        ↓
GPT-4o-mini vision → { summary, screen_type, key_entities, confidence }
        ↓
Significant change? (share started / stopped / type changed)
   YES → Tier 1: conversation.item.create
         [SCREEN EVENT] injected into LLM conversation history
         Bot can answer "Can you see my screen?" correctly ✅
   ALL  → Tier 2: session.update (instructions only)
         Background context silently updated for all future turns ✅
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
| Screen vision | GPT-4o-mini vision + Playwright screenshot + perceptual hash diff |
| Vision injection | Dual-tier: `conversation.item.create` + `session.update` |
| Prompt generation | GPT-4o-mini (interview plan) + hardcoded vision + voice rule blocks |
| Meet creation | Google Calendar API (bot = host, no Quick Access restriction) |
| API | FastAPI + Uvicorn |
| Frontend | React + Vite + shadcn/ui |
| Web server | Nginx (reverse proxy) |
| Audio routing | PulseAudio virtual cables inside Docker (per-session isolated) |
| Deployment | Docker + Docker Compose on AWS EC2 |
| Public URL | Cloudflare Tunnel (cloudflared) |

---

## 📁 Project Structure

```
INT-interview-Bot/
├── Backend/
│   ├── api.py              FastAPI — sessions, routing, subprocess management
│   ├── main.py             Per-session orchestrator — Meet + Vision + Realtime tasks
│   ├── join_meet.py        Playwright — joins Meet, exposes page to VisionWorker
│   ├── realtime.py         GPT Realtime WebSocket — STT + LLM + dual-tier vision injection
│   ├── llm_tts.py          Cartesia TTS + barge-in interrupt
│   ├── make_prompt.py      Master prompt: interview plan + vision block + voice rules
│   ├── screen_context.py   Per-session vision context store (live events + background)
│   ├── vision_capture.py   Playwright screenshot capture (PNG bytes)
│   ├── vision_diff.py      Perceptual hash diff detection (skips unchanged frames)
│   ├── vision_worker.py    Async vision worker: capture → diff → analyze → inject
│   ├── meet_creator.py     Google Calendar API Meet link creator (bot = host)
│   ├── setup_login.py      ONE-TIME: Google login setup after docker-compose up
│   ├── credentials.json    Google OAuth2 client secret (from Google Cloud Console)
│   ├── token.json          Pre-authorized OAuth2 token (generated via get_token.py)
│   ├── requirements.txt    Python dependencies (includes Pillow for vision diff)
│   ├── Dockerfile          python:3.11-slim + Chrome + PulseAudio + noVNC
│   └── start.sh            Container startup: Xvfb → noVNC → PulseAudio → FastAPI
├── Frontend/
│   ├── src/pages/Index.tsx   Main UI — form, persona preview, session management
│   └── dist/                 Built output served by Nginx
├── docker-compose.yaml
├── nginx.conf
└── Readme.md
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

# Google Calendar API (Meet creation — bot = host)
GOOGLE_CREDENTIALS_PATH=/app/credentials.json
GOOGLE_TOKEN_PATH=/app/token.json

# Audio tuning
SILENCE_DURATION_MS=700
VOICE_THRESHOLD=0.05
POST_TTS_COOLDOWN=1.0
STT_DEVICE_INDEX=0
TTS_DEVICE_INDEX=0

# Vision pipeline (optional — these are the defaults)
VISION_MODEL=gpt-4o-mini
VISION_CAPTURE_INTERVAL=1.0
VISION_DIFF_THRESHOLD=0.05
VISION_MAX_PER_MINUTE=15
VISION_CONTEXT_CHECK_INTERVAL=1.0
```

---

## 🐳 Docker Ports

| Port | Service | URL |
|------|---------|-----|
| **4011** | React frontend (Nginx) | `http://YOUR_IP:4011` |
| **4012** | FastAPI backend API | `http://YOUR_IP:4012` |
| **4012** | API Docs (Swagger) | `http://YOUR_IP:4012/docs` |
| **4013** | noVNC debug viewer | `http://YOUR_IP:4013/vnc.html` |

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
# Open http://localhost:4013/vnc.html → log into Google → script exits automatically

# 6. Open the UI
# http://localhost:4011
```

---

## 🌐 EC2 Deployment

```bash
# SSH into server
ssh ubuntu@YOUR_EC2_IP
cd ~/INT-interview-Bot

# Pull latest
git pull

# Full rebuild (if Dockerfile or requirements.txt changed):
docker compose down
docker compose build --no-cache
docker compose up -d

# Fast redeploy (if only .py files changed — no rebuild needed):
docker cp Backend/main.py int-avatar-bot:/app/main.py
# repeat for any changed files...
docker compose restart backend

# Frontend only (no Docker restart needed):
cd Frontend && npm run build && cd ..
# Nginx volume-mounts dist/ — change is live immediately

# After any rebuild:
docker exec -it int-avatar-bot python /app/setup_login.py
```

**AWS Security Group — open these ports:**

| Port | Type |
|------|------|
| 22 | SSH |
| 4011 | Custom TCP |
| 4012 | Custom TCP |
| 4013 | Custom TCP |

---

## 🔊 Audio Architecture

```
TTS FLOW (Alex speaks into Meet):
  llm_tts.py → Cartesia API → WAV bytes
  → paplay --device=VMic_{sid}
  → VMic_{sid}.monitor → VMicSrc_{sid}
  → Chrome mic → Meet participants hear Alex ✅

STT FLOW (bot hears candidate):
  Candidate speaks → Chrome audio output → VSpk_{sid} sink
  → VSpk_{sid}.monitor
  → sounddevice InputStream @ 44100Hz
  → resample to 24000Hz in Python
  → GPT Realtime WebSocket (STT + LLM) ✅

CRITICAL RULES — DO NOT CHANGE:
  samplerate = 44100Hz   — PulseAudio native rate; any other value = silence
  headless = False       — Chrome disables audio in headless mode
  Default sink = VSpk    — NEVER set default to VMic (causes TTS echo loop)
  Per-session sinks      — each session gets VMic_{sid8} / VSpk_{sid8} / VMicSrc_{sid8}
```

---

## 👁 Vision Architecture

### How the bot sees the candidate's screen

```
STEP 1 — CAPTURE (every 1.0s, async, never blocks voice)
  join_meet.py owns the Playwright page object
  → page_holder list shares it with VisionWorker after join
  → vision_capture.py: page.screenshot(full_page=False) → PNG bytes

STEP 2 — DIFF DETECTION (cost control — prevents unnecessary API calls)
  vision_diff.py: perceptual hash (average hash, 8×8 = 64 bits)
  → Hamming distance between current and previous frame
  → diff_score = differing_bits / 64
  → diff_score < 0.05 → SKIP (screen unchanged, no API call)
  → diff_score ≥ 0.05 → ANALYZE

STEP 3 — VISION ANALYSIS (runs in thread pool — event loop never blocked)
  vision_worker.py → GPT-4o-mini vision (detail="auto")
  → Returns JSON:
    {
      "summary":          "1-2 sentence description of what is visible",
      "screen_type":      "code | document | slide | browser | video | empty | unknown",
      "key_entities":     ["up to 5 specific items visible"],
      "raw_text_excerpt": "up to 150 chars of key visible text",
      "confidence":       0.0 – 1.0
    }
  → Max 15 API calls/min (VISION_MAX_PER_MINUTE)

STEP 4 — CONTEXT INJECTION (realtime.py, every 1.0s)

  Tier 1 — Significant change only:
    Triggers: sharing_started | sharing_stopped | type_changed
    Method: conversation.item.create
    Effect: [SCREEN EVENT] goes into LLM conversation HISTORY
    Result: Bot treats it as something it witnessed — can reference it naturally
    Example: Candidate asks "Can you see my screen?" → bot answers YES + describes it ✅

  Tier 2 — Every new analysis:
    Method: session.update (instructions field only)
    Effect: Background context silently updated (no conversation history entry)
    Result: Bot has current screen state as persistent background knowledge ✅
```

### Why two tiers?

| | Tier 1 (conversation.item.create) | Tier 2 (session.update) |
|--|---|---|
| What it is | Live event in conversation history | Silent background instruction update |
| When it fires | Significant change only | Every new analysis |
| "Can you see my screen?" | ✅ Bot answers correctly | ❌ May or may not reference it |
| Frequency | Rare (share start/stop/type) | Every analyzed frame |

---

## 📋 Master Prompt Structure

Every session prompt is built in three mandatory sections:

```
Section 1 — Interview Identity + Structure
  Generated by GPT-4o-mini (or rule-based fallback)
  → Interviewer name, tone, opening line
  → Interview phases with timing and role-specific questions

Section 2 — Screen Vision Capability  [ALWAYS HARDCODED]
  → Bot knows it has real-time screen vision during interviews
  → Knows [SCREEN EVENT] messages are its own live observations
  → Knows how to answer "Can you see my screen?" → YES + describe
  → Knows how to weave code / slides / documents into questions naturally

Section 3 — Voice Conversation Rules  [ALWAYS HARDCODED]
  → Max 2-3 sentences per response
  → One question at a time, never stack two
  → No hollow filler phrases ("Absolutely!", "Great question!")
  → Barge-in awareness — stop when interrupted, don't re-read
```

Sections 2 and 3 are **never delegated to GPT** because they are operational constraints that must be identical and always present across every session.

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

## 🛠️ Useful Commands

```bash
# Live logs (vision logs included)
docker logs -f int-avatar-bot

# Check active sessions
curl http://YOUR_IP:4012/sessions

# Health check
curl http://YOUR_IP:4012/health

# Debug audio sinks
docker exec int-avatar-bot pactl list sinks short
docker exec int-avatar-bot pactl list sources short

# Verify Pillow installed (required for vision diff)
docker exec int-avatar-bot python -c "from PIL import Image; print('Pillow OK')"

# Monitor resource usage
docker stats int-avatar-bot

# Stop everything
docker compose down

# Full rebuild
docker compose build --no-cache && docker compose up -d
```

### Vision log reference
```bash
# Worker started
[VISION] 🚀 [f5b7a73f] Worker started. model=gpt-4o-mini | interval=1.0s | max=15/min

# Frame analyzed
[VISION] 👁  [f5b7a73f] slide (conf=0.9): The screen shows a slide titled 'Top LLMs in 2026'

# Significant change → Tier 1 queued
[VISION] 🔔 [f5b7a73f] Significant change (sharing_started) → live event queued

# Tier 1 injected into conversation history
[RT] 🔔 [f5b7a73f] Tier1 live event injected → "[SCREEN EVENT] The screen shows..."

# Tier 2 background context updated
[RT] 👁  [f5b7a73f] Tier2 background updated → "The screen shows a slide titled..."

# Unchanged frame skipped (no API call)
# (no log — silently skipped by diff detection)

# Rate cap hit
[VISION] ⏸  [f5b7a73f] Rate cap (15/min) — skipping
```

---

## 🌍 Public URL (Cloudflare Tunnel)

```bash
# Expose frontend publicly (Windows)
cloudflared-windows-amd64.exe tunnel --protocol http2 --url http://localhost:4011
# Gets: https://random-words.trycloudflare.com
```

> URL changes on every restart. For a permanent URL, attach a domain in Cloudflare.

---

## 🗺️ Roadmap

- [x] Multi-session voice interview bot with Google Meet as host
- [x] Barge-in / interruption support
- [x] Real-time screen vision (capture → diff → GPT-4o-mini analysis)
- [x] Dual-tier context injection (live conversation events + background)
- [x] Vision-aware master prompt (bot knows it can see the screen)
- [ ] **AI Avatar video with lip-sync** (HeyGen LiveAvatar Lite — next priority)
- [ ] Session transcripts saved to disk / database
- [ ] Chrome profile persistence across rebuilds (named Docker volume)
- [ ] GPT Realtime quality / VAD tuning per session

---

## ⚠️ Important Notes

- Never commit `Backend/.env` — it contains API keys
- The bot uses a dedicated Google account — never use a personal account
- `Frontend/dist/` must be built before `docker-compose up`
- noVNC (port **4013**) is for debugging only — do not expose publicly
- After every full `docker compose build --no-cache`, re-run `setup_login.py` (Chrome profile is reset)
- Vision calls use OpenAI API credits (GPT-4o-mini vision) — monitor with `VISION_MAX_PER_MINUTE`
- Each session runs Chrome + GPT Realtime WebSocket + VisionWorker — monitor with `docker stats`

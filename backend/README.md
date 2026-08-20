# AI Smart Mirror — Backend (Modules 1 & 2)

FastAPI backend implementing:
- **Module 1 — AI Fashion Recommendation System**: MediaPipe body/face landmarks →
  body shape, face shape, skin tone → FashionCLIP-powered inventory recommendations
  with explanations.
- **Module 2 — Conversational Smart Stylist**: Whisper STT → LangGraph agent
  (Ollama LLM) → Edge-TTS, with NLP extraction of occasion/formality/location/time.

## 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally
- A [Supabase](https://supabase.com) project (free tier is fine)
- `ffmpeg` installed on PATH (required by faster-whisper)

## 2. Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Pull the LLM model
ollama pull qwen2.5:7b

cp .env.example .env
# edit .env: fill in SUPABASE_URL and SUPABASE_KEY from your Supabase project settings
```

## 3. Database setup

In the Supabase SQL editor, run `app/db/schema.sql` once. It creates all tables
(users, sessions, scans, inventory, conversations, feedback) and the
`match_inventory` pgvector search function.

In Supabase Storage, create a bucket named `inventory-media` (match `SUPABASE_BUCKET`
in `.env`), public read access.

## 4. Seed inventory (optional but needed for recommendations to return results)

Put product photos in `data/images/`, edit `data/inventory_seed.csv` to match, then:

```bash
python scripts/embed_inventory.py
```

## 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Docs at `http://localhost:8000/docs`.

## 6. API summary

| Endpoint | Method | Module | Purpose |
|---|---|---|---|
| `/api/session` | POST | - | Create a new mirror session |
| `/api/vision/scan` | POST | 1 | Upload a camera frame → body shape, face shape, skin tone |
| `/api/recommend` | POST | 1 | Get recommended items for a session (uses latest scan) |
| `/api/voice/stt` | POST | 2 | Upload audio → transcript |
| `/api/voice/tts` | POST | 2 | Text → MP3 audio stream |
| `/api/chat` | POST | 2 | Send a message → agent reply + extracted context |

## 7. Typical frontend flow

1. `POST /api/session` on mirror wake → get `session_id`
2. Capture a camera frame every few seconds → `POST /api/vision/scan`
3. User speaks → record audio → `POST /api/voice/stt` → get text
4. `POST /api/chat` with that text → get `reply` (and extracted occasion/formality/etc.)
5. `POST /api/voice/tts` with `reply` → play the returned audio
6. `POST /api/recommend` any time to (re)pull ranked items for the current session

## 8. Where each GitHub repo is used

See the handoff documents provided alongside this backend (AI_Smart_Mirror_Project_Spec.docx,
Frontend_Integration_Guide.docx, and the Module_1_2/Handsfree addendums) for the full
repo-to-module mapping, architecture rationale, and phased build order. These are delivered
separately from this zip -- if they aren't in your project folder, they were provided in
the chat conversation that produced this backend, not inside this archive.

# AI Smart Mirror — Backend

FastAPI backend for an in-store smart mirror. Five modules:

- **Module 1 — Body/face scan**: MediaPipe landmarks → body shape, face shape, skin tone
  (depth + undertone), height, body size, glasses, hair length; gender via an ensemble
  (FashionCLIP zero-shot + DeepFace, see `services/vision/gender_detect.py`).
- **Module 2 — Conversational stylist "Aria"**: Groq-hosted LLM with a bounded
  tool-calling loop (`services/agent/graph.py`), streaming replies, cross-turn memory,
  cart awareness. Whisper STT and Edge-TTS for voice.
- **Module 3 — Recommendations**: Marqo-FashionCLIP embeddings + pgvector retrieval
  (Stage A), rule-based compatibility re-ranking (Stage B), styled looks by garment type,
  feedback signals, cold start, trends, A/B-tested ranking weights.
- **Module 4 — Weather-aware nudges** (OpenWeatherMap, optional).
- **Module 5 — Staff escalation**: customer requests pushed to a staff screen over WebSocket.

## 1. Prerequisites

- Python 3.12
- A [Supabase](https://supabase.com) project (free tier is fine — but it **pauses after
  7 days without activity**; if the project host stops resolving, restore it from the
  Supabase dashboard)
- A [Groq](https://console.groq.com) API key (free tier: 200K tokens/day **per model**)
- `ffmpeg` on PATH (required by faster-whisper)

## 2. Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate           # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Fill in `SUPABASE_URL`, `SUPABASE_KEY` and `GROQ_API_KEY` in `.env`. Everything else has
working defaults. Model split (see `app/config.py`):

- `GROQ_MODEL` (`openai/gpt-oss-120b`) — structured/tool-calling turns. Keep it on 120b;
  20b was unreliable for structured output.
- `GROQ_FAST_MODEL` (`openai/gpt-oss-20b`) — plain chit-chat and "why this item?"
  explanations. A separate model means a separate daily quota.

### Face-shape model weights (one-time, optional)

The trained face-shape classifier (`app/services/vision/face_shape_ml/`, vendored from
Diksha-cmd/face-shape-prediction, MIT) needs two Git-LFS files from the upstream repo:

```bash
git lfs install
git clone https://github.com/Diksha-cmd/face-shape-prediction.git /tmp/faceshape-src
mkdir -p data/models/face_shape
cp /tmp/faceshape-src/models/faceshape_facenet_v3.keras data/models/face_shape/
cp /tmp/faceshape-src/models/face_landmarker.task data/models/face_shape/
```

Without them, face shape falls back to the geometric heuristic in `face_shape.py`.

## 3. Database setup

In the Supabase SQL editor run, in order:

1. `app/db/schema.sql`
2. `app/db/module3_missing_migrations.sql` (bulk-update RPCs, gender column,
   `match_inventory(..., match_gender)`, HNSW index)

There is no direct Postgres connection from the app — only the REST/RPC API — so
migrations are always pasted into the SQL editor.

## 4. Seed the catalog

```bash
python scripts/seed_fashion_dataset.py          # inventory rows + text embeddings
python scripts/backfill_season_year.py
python scripts/backfill_gender.py
python scripts/backfill_product_images.py       # photos -> data/product_images/ (gitignored)
python scripts/upgrade_product_images_hq.py     # 384x512 versions of the same photos
python scripts/backfill_image_embeddings.py     # image embeddings; resumable (~1-2h CPU)
```

Product photos are served from local disk at `/media/products`, not Supabase Storage.

## 5. Run

```bash
python -m uvicorn app.main:app --reload --port 8000
```

First start takes a few minutes while models warm up. API docs at
`http://localhost:8000/docs`.

## 6. Tests

```bash
python -m pytest -q
```

`TestNaturalLanguageExtraction` calls the real Groq API (skipped without a key; fails
with 429s once the daily quota is spent). Deselect it with
`-k "not TestNaturalLanguageExtraction"`.

## 7. API summary

| Endpoint | Method | Module | Purpose |
|---|---|---|---|
| `/api/session` | POST | - | Create a mirror session |
| `/api/vision/scan` | POST | 1 | Camera frame → body/face/skin/gender profile |
| `/api/vision/scan/gender` | POST | 1 | Customer corrects the detected department |
| `/api/vision/calibrate` | POST | 1 | Height calibration |
| `/api/vision/presence` | POST | 1 | Is someone in front of the mirror? |
| `/api/recommend` | POST | 1/3 | Recommendations for the latest scan (`grouped`, `include`, `occasion`...) |
| `/api/outfit-recommendation/{session_id}` | GET | 3 | Outfit built from session context |
| `/api/inventory/browse` | GET | 3 | Catalog browsing (category, occasion filters) |
| `/api/inventory/categories`, `/occasions` | GET | 3 | Filter values |
| `/api/user-context/{session_id}` | GET | 1+2 | Merged scan + conversation profile |
| `/api/chat`, `/api/chat/stream` | POST | 2 | Talk to Aria (SSE streaming variant) |
| `/api/agent/event` | POST | 2 | Proactive triggers (`scan_complete`, `item_liked`...) |
| `/api/voice/stt`, `/api/voice/tts` | POST | 2 | Speech to text / text to speech |
| `/api/events`, `/api/events/batch` | POST | 3 | Interaction logging (feeds feedback + A/B reports) |
| `/api/staff/requests` | GET | 5 | Open staff requests |
| `/api/staff/requests/{id}/status` | POST | 5 | Update a request |
| `/api/staff/ws` | WS | 5 | Live push to the staff screen |

## 8. Typical flow

1. `POST /api/session` when a customer is detected
2. `POST /api/vision/scan` → profile; the frontend then fires `POST /api/agent/event`
   with `scan_complete` so Aria recommends a full look
3. Customer talks → `/api/voice/stt` → `/api/chat/stream` → `/api/voice/tts`
4. Clicks, try-ons and cart adds go to `/api/events`, which feed later rankings

## 9. Useful scripts

- `scripts/report_ab_test.py` — engagement per ranking-weights variant
- `scripts/check_training_readiness.py` / `scripts/train_two_tower.py` — two-tower model
  (trained, not yet used for serving)

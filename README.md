# AI Smart Mirror

AI stylist for a physical clothing store: the mirror scans the customer (body shape, face
shape, skin tone, height), recommends complete looks from the store's catalog, and lets
them talk to "Aria", a conversational stylist that can search, recommend, add to cart,
start virtual try-on and call a staff member.

- **Frontend** — React (Create React App), this folder (`src/`)
- **Backend** — FastAPI, in [`backend/`](backend/README.md) (setup, database, API reference)

## Run locally

Backend (port 8000), see `backend/README.md` for first-time setup:

```bash
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Frontend (port 3000):

```bash
npm install
npm start
```

Open http://localhost:3000 in Chrome or Edge. The "Start Your Shift" sign-in is a mock
gate. Camera features (body scan, presence detection, virtual try-on) need a real browser
with camera access.

Frontend settings live in `.env` (e.g. `REACT_APP_ARIA_VOICE=off` mutes Aria's voice;
restart `npm start` after changing it).

## Scripts

- `npm start` — dev server
- `npm run build` — production build into `build/`
- `npm test` — frontend tests

## Project docs

- `HANDOFF_MODULE3.md` — current status, recent changes and open issues
- `AI_Smart_Mirror_Handover.docx` — onboarding guide for new developers

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import vision, recommend, voice, chat, agent_events, user_context, outfit_recommendation, staff, inventory, events


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Warm up every model ONCE at server startup instead of on a user's first
    request. This is critical for the sub-1-second scan requirement -- without
    this, the first /api/vision/scan after a restart would eat several extra
    seconds loading the glasses classifier, and the first /api/chat or
    /api/voice/tts call would eat seconds loading Whisper/FashionCLIP.
    """
    print("Warming up models...")

    try:
        # The Supabase client itself is cheap (get_supabase() is just an
        # HTTP client object) -- the real cost is the FIRST network round-trip
        # to Supabase's Postgres/PostgREST endpoint (TLS handshake + cold
        # connection), measured live at ~6 SECONDS, vs. ~0.3s for every call
        # after. Every request handler that touches the DB (scan, chat, ...)
        # was paying that cold-start cost on whichever request happened to be
        # first -- for a demo, that's almost always the very first scan or
        # chat message, i.e. the worst possible moment for it to be slow.
        # One throwaway query here pays that cost once, at boot.
        from app.db.supabase_client import get_mirror_calibration
        get_mirror_calibration()
        print("  Supabase connection warm")
    except Exception as e:
        print(f"  Supabase warmup skipped (first real DB call will be slower): {e}")

    try:
        from app.services.vision.accessory_detect import _get_glasses_classifier
        _get_glasses_classifier()
        print("  glasses-detector ready")
    except Exception as e:
        print(f"  glasses-detector skipped: {e}")

    try:
        # Unlike DeepFace's gender model below, this one's weights are already
        # local (vendored into data/models/face_shape/, not downloaded on
        # first use) -- nothing here blocks on a slow network fetch, so
        # there's no reason to defer it and eat ~90s on some user's first
        # scan of the day instead of once at startup.
        from app.services.vision.face_shape import _get_face_shape_model
        _get_face_shape_model()
        print("  face-shape model ready")
    except Exception as e:
        print(f"  face-shape model skipped (will fall back to the geometric heuristic): {e}")

    # LOAD-ORDER CONSTRAINT: the face-shape model above imports TensorFlow,
    # and it MUST stay ahead of anything that loads PyTorch (FashionCLIP).
    # Importing TensorFlow after PyTorch segfaults this process (reproduced
    # 2026-09-19); gender_detect.py's ensemble also enforces tf-before-torch.
    # FashionCLIP/Whisper warmup temporarily skipped at startup -- their weights
    # are still downloading on this connection and would block server startup
    # for a long time. Both load lazily (lru_cache) on first real call to
    # /api/recommend or /api/voice/stt instead. DeepFace's gender model is the
    # same story (its own internal weight download, separate from the
    # tensorflow import), so it's deferred too rather than eating startup time.
    print("  FashionCLIP warmup deferred (loads lazily on first /api/recommend call)")
    print("  faster-whisper warmup deferred (loads lazily on first /api/voice/stt call)")
    print("  DeepFace gender model warmup deferred (loads lazily on first /api/vision/scan call)")

    print("Server ready (some models may still be loading).")
    yield


app = FastAPI(
    title="AI Smart Mirror - Backend",
    description="Modules 1 (AI Fashion Recommendation) and 2 (Conversational Smart Stylist)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Product photos (scripts/backfill_product_images.py) -- served straight
# from local disk rather than Supabase Storage. That storage path is
# network-bound at ~5-12s/upload (see seed_fashion_dataset.py's own docstring),
# which for 37K catalog items is 50+ hours; this whole app already only ever
# runs as a local kiosk (backend/frontend both on localhost), so a local
# static mount gets real photos into the UI in minutes with the exact same
# `image_url` contract every consumer (frontend, agent tools) already expects.
_PRODUCT_IMAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "product_images"
_PRODUCT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/products", StaticFiles(directory=_PRODUCT_IMAGES_DIR), name="product_images")

app.include_router(vision.router)
app.include_router(recommend.router)
app.include_router(voice.router)
app.include_router(chat.router)
app.include_router(agent_events.router)
app.include_router(user_context.router)
app.include_router(outfit_recommendation.router)
app.include_router(staff.router)
app.include_router(inventory.router)
app.include_router(events.router)


@app.get("/")
def health():
    return {"status": "ok", "env": settings.app_env}


@app.post("/api/session")
def new_session():
    from app.db.supabase_client import create_session
    session = create_session()
    return session

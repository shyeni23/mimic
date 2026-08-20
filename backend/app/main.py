from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import vision, recommend, voice, chat, agent_events, user_context


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
        from app.services.vision.accessory_detect import _get_glasses_classifier
        _get_glasses_classifier()
        print("  glasses-detector ready")
    except Exception as e:
        print(f"  glasses-detector skipped: {e}")

    # FashionCLIP/Whisper warmup temporarily skipped at startup -- their weights
    # are still downloading on this connection and would block server startup
    # for a long time. Both load lazily (lru_cache) on first real call to
    # /api/recommend or /api/voice/stt instead.
    print("  FashionCLIP warmup deferred (loads lazily on first /api/recommend call)")
    print("  faster-whisper warmup deferred (loads lazily on first /api/voice/stt call)")

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

app.include_router(vision.router)
app.include_router(recommend.router)
app.include_router(voice.router)
app.include_router(chat.router)
app.include_router(agent_events.router)
app.include_router(user_context.router)


@app.get("/")
def health():
    return {"status": "ok", "env": settings.app_env}


@app.post("/api/session")
def new_session():
    from app.db.supabase_client import create_session
    session = create_session()
    return session

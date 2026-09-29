from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute, not cwd-relative: pydantic-settings resolves a plain ".env" against
# the process's current working directory, not this file's location -- fine
# when launched via run_server.bat (which `cd`s into backend/ first), but
# breaks when started from elsewhere (e.g. the repo root, which has its own
# unrelated .env for the React frontend's REACT_APP_* vars) and silently loads
# the wrong file instead of erroring, which is worse. Pinning to this file's
# own directory makes backend/.env resolve correctly regardless of cwd.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_bucket: str = "inventory-media"

    # Ollama (kept as fallback / for other local-model experiments)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Groq (cloud LLM -- used by the agent, see app/services/agent/llm.py)
    groq_api_key: str = ""
    # openai/gpt-oss-120b: the flagship reasoning model. Tested a swap to
    # gpt-oss-20b for speed -- was actually WORSE (10-60s latency, frequent
    # JSON schema validation failures producing "Sorry, I hit a snag" replies).
    # Sticking with 120b as the reliable choice; speed comes from streaming
    # + non-structured chat path instead.
    groq_model: str = "openai/gpt-oss-120b"
    # "Path B" experiment (see app/services/agent/graph_native.py) -- native
    # bind_tools() tool-calling on a smaller model, compared head-to-head
    # against Path A's structured-output loop (graph.py) on gpt-oss-120b,
    # which already failed two live bind_tools() reliability attempts.
    # NOTE: external research this session found llama-3.1-8b-instant/
    # llama-3.3-70b-versatile working reliably for native tool-calling on
    # Groq elsewhere, but neither exists on THIS account/region (confirmed
    # live via the Groq /models list -- no meta-llama chat models are
    # present at all here, just the openai/gpt-oss family, qwen/qwen3.6-27b,
    # allam-2-7b, and groq/compound*). gpt-oss-20b is the closest real
    # option: the smaller sibling of Path A's own model, same vendor/family,
    # which minimizes confounding variables versus jumping to an untested
    # architecture. Re-run `client.models.list()` if this ever 404s again --
    # do not guess a model name, this project has been burned by that twice.
    groq_native_model: str = "openai/gpt-oss-20b"
    # Model for plain (non-structured, tool-less) calls: graph.py's fast chat
    # path and llm_explain.py. The 20b's weakness above was STRUCTURED output;
    # these calls are free text, so it's the low-risk place to use it. Groq's
    # free-tier 200K tokens/day quota is PER MODEL, so this moves chit-chat
    # onto its own bucket and leaves 120b's quota for tool/structured turns.
    # Set to "" to put everything back on groq_model.
    groq_fast_model: str = "openai/gpt-oss-20b"

    # Whisper
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # Pinned rather than auto-detected: on short/compressed mic clips, Whisper's
    # own language-detection step is unreliable (observed live guessing "Korean"
    # at 32% confidence on a plain test tone) -- a wrong guess doesn't just hurt
    # accuracy, it transcribes real English speech using an entirely different
    # language's sound patterns, producing text unrelated to what was said.
    whisper_language: str = "en"

    # TTS
    tts_voice: str = "en-US-JennyNeural"

    # Fashion CLIP -- Marqo/marqo-fashionCLIP (Apache-2.0, ViT-B-16, 512-dim,
    # ~+57% over patrickjohncyh's original fashion-clip on the same benchmarks).
    # Loaded via open_clip in fashion_clip.py. Both output 512-dim vectors so
    # the pgvector column doesn't change size when swapping models, but you
    # MUST re-run scripts/embed_inventory.py after switching -- vectors from
    # different embedding spaces are not comparable.
    fashion_clip_model: str = "Marqo/marqo-fashionCLIP"

    # Weather (Module 4 -- see app/services/weather.py) -- OpenWeatherMap free
    # tier (1000 calls/day, no card required: https://openweathermap.org/api).
    # Empty by default: get_weather() falls back to a graceful "not configured"
    # response rather than raising, same pattern as every other optional
    # integration in this project (FashionCLIP/DeepFace weight-missing paths).
    openweather_api_key: str = ""

    # DEMO / STORE-SPECIFIC: force every scan into one department. "female"
    # = the mirror only ever recommends women's (and unisex) items and the
    # detected gender is ignored; the Range toggle on the Recommendations
    # page is hidden. Empty = use the gender ensemble (gender_detect.py).
    # Set FORCE_GENDER=female in .env. Kids' items stay excluded either way.
    force_gender: str = ""
    # The mirror's fixed physical location -- weather is about where the
    # STORE is, not the customer, so this is a deployment setting, not
    # something extracted from conversation. City name (OpenWeatherMap
    # resolves it) is simplest; switch to lat/lon if the city is ambiguous.
    mirror_location: str = "New York,US"

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

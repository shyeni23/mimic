from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_bucket: str = "inventory-media"

    # Ollama (kept as fallback / for other local-model experiments)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Groq (cloud LLM -- used by the agent, see app/services/agent/llm.py)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Whisper
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # TTS
    tts_voice: str = "en-US-JennyNeural"

    # FashionCLIP
    fashion_clip_model: str = "patrickjohncyh/fashion-clip"

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

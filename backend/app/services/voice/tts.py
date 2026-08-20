"""
Text-to-speech via edge-tts (Microsoft Edge's online neural TTS, free, no API key).
Returns raw MP3 bytes so the router can stream them straight back to the frontend.
"""
import io
import edge_tts

from app.config import settings


async def synthesize_speech(text: str, voice: str | None = None, rate: str = "+0%") -> bytes:
    communicate = edge_tts.Communicate(text=text, voice=voice or settings.tts_voice, rate=rate)
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    return buffer.getvalue()


async def list_voices(locale_prefix: str = "en-") -> list[dict]:
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith(locale_prefix)]

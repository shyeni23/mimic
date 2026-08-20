from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
import io

from app.services.voice.stt import transcribe_audio_bytes
from app.services.voice.tts import synthesize_speech
from app.models.schemas import TTSRequest

router = APIRouter(prefix="/api/voice", tags=["voice (Module 2)"])


@router.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """Upload a recorded audio clip (wav/mp3/webm), get back the transcript."""
    audio_bytes = await audio.read()
    try:
        result = transcribe_audio_bytes(audio_bytes, filename_hint=audio.filename or "audio.wav")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Speech-to-text model not ready yet: {e}")
    return result


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """Convert text to speech, streamed back as MP3 bytes for the frontend to play."""
    audio_bytes = await synthesize_speech(req.text, voice=req.voice)
    return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/mpeg")

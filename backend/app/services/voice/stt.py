"""
Speech-to-text via faster-whisper (CTranslate2-based Whisper, much faster than
the original openai-whisper package on CPU -- important since this runs on
the mirror's local machine alongside everything else).
"""
import os
import tempfile
from functools import lru_cache

from faster_whisper import WhisperModel

from app.config import settings


@lru_cache
def get_model() -> WhisperModel:
    """
    Local cache ONLY (local_files_only=True) so that if the model hasn't
    finished downloading yet, this fails in milliseconds instead of hanging on
    a slow/stalled connection -- callers catch the failure and degrade
    gracefully. Once the weights are actually cached (via a deliberate one-time
    download), this same call starts succeeding automatically.
    """
    return WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        local_files_only=True,
    )


def transcribe_audio_bytes(audio_bytes: bytes, filename_hint: str = "audio.wav") -> dict:
    model = get_model()
    suffix = "." + filename_hint.rsplit(".", 1)[-1] if "." in filename_hint else ".wav"

    # delete=False + manual cleanup: on Windows, a NamedTemporaryFile opened
    # with delete=True holds an exclusive lock, so faster-whisper/ffmpeg can't
    # open the same path by name while our handle is still open.
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.flush()
        tmp.close()
        # beam_size=1 (greedy decoding) instead of the default 5 -- on this
        # CPU-constrained machine beam search multiplies transcription time
        # for a real-time voice UI with negligible accuracy loss on short
        # conversational utterances.
        segments, info = model.transcribe(tmp.name, beam_size=1, vad_filter=True)
        text_segments = list(segments)
    finally:
        os.unlink(tmp.name)

    full_text = " ".join(seg.text.strip() for seg in text_segments).strip()
    return {
        "text": full_text,
        "language": info.language,
        "language_probability": info.language_probability,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text.strip()} for s in text_segments
        ],
    }

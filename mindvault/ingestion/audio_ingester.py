"""Audio transcription — Groq Whisper API (cloud) or faster-whisper (local).

Provider is selected via the STT_PROVIDER environment variable:
  groq           — Recommended. Free cloud API, no native DLLs, no ffmpeg needed.
                   Requires GROQ_API_KEY (free at https://console.groq.com).
  faster_whisper — Local inference. Requires ffmpeg on PATH. May be blocked by
                   Windows Smart App Control on some machines.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mindvault.config import GROQ_API_KEY, STT_PROVIDER, WHISPER_MODEL_SIZE

_model = None


def _get_local_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_bytes: bytes, language: str | None = None) -> str:
    """Transcribe audio bytes to text using the configured STT provider."""
    if STT_PROVIDER == "groq":
        return _transcribe_groq(audio_bytes, language)
    return _transcribe_local(audio_bytes, language)


def _transcribe_groq(audio_bytes: bytes, language: str | None = None) -> str:
    """Transcribe via Groq Whisper API. Free tier: 7,200 audio seconds/day."""
    import httpx

    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
            "and add GROQ_API_KEY=gsk_... to your .env file."
        )

    files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
    data: dict = {"model": "whisper-large-v3-turbo"}
    if language:
        data["language"] = language

    response = httpx.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files=files,
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("text", "")


def _transcribe_local(audio_bytes: bytes, language: str | None = None) -> str:
    """Transcribe locally via faster-whisper. Requires ffmpeg on PATH.

    faster-whisper only accepts a file path, not an in-memory byte stream, so
    the audio is written to a temporary file.  The finally block guarantees
    deletion even when transcription raises an exception.
    """
    model = _get_local_model()

    # delete=False is necessary on Windows because faster-whisper opens the
    # file by path while the NamedTemporaryFile handle is still open; Windows
    # does not allow a second open on a file that has not been closed yet.
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        kwargs: dict = {"beam_size": 5}
        if language:
            kwargs["language"] = language
        segments, _ = model.transcribe(tmp_path, **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

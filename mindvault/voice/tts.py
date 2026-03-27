"""Text-to-speech — gTTS, returns in-memory MP3 as BytesIO."""
from __future__ import annotations

import io

from gtts import gTTS

_MAX_CHARS = 3000  # gTTS free endpoint limit per request


def synthesize(text: str, lang: str = "en") -> io.BytesIO:
    """
    Convert text to speech using gTTS (Google free TTS endpoint).
    Returns an in-memory BytesIO containing an MP3 stream.
    No API key required.
    """
    # Truncate very long text to avoid timeouts
    text = text[:_MAX_CHARS].strip()
    if not text:
        return io.BytesIO()

    tts = gTTS(text=text, lang=lang, slow=False)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf

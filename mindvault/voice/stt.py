"""Speech-to-text — lazy singleton WhisperModel."""
from __future__ import annotations

# Re-exports the shared transcription function so voice/stt.py is the
# canonical in-app STT entry point, while ingestion/audio_ingester.py
# handles file-based batch ingestion.
from mindvault.ingestion.audio_ingester import transcribe as transcribe  # noqa: F401

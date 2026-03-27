"""Central configuration — env vars, path constants, shared settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

# ── Voice ─────────────────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")

# STT provider: "groq" (recommended, cloud, free) or "faster_whisper" (local, requires ffmpeg)
STT_PROVIDER: str = os.getenv("STT_PROVIDER", "groq")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

# ── Interview ─────────────────────────────────────────────────────────────────
EXTRACTION_INTERVAL: int = int(os.getenv("EXTRACTION_INTERVAL", "3"))

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR: Path = Path(__file__).parent.parent
DATA_DIR: Path = ROOT_DIR / os.getenv("DATA_DIR", "data")
CHROMA_DIR: Path = DATA_DIR / "chroma"
UPLOADS_DIR: Path = DATA_DIR / "uploads"
DB_PATH: Path = DATA_DIR / "mindvault.db"
PROMPTS_DIR: Path = ROOT_DIR / "prompts"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")

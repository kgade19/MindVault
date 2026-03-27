"""Interview agent — builds messages, tracks phase, triggers mid-interview extraction."""
from __future__ import annotations

from mindvault.config import EXTRACTION_INTERVAL, load_prompt
from mindvault.database import sqlite_db as db


def build_system_prompt(expert: dict, turn_count: int) -> str:
    """
    Load and populate the interview system prompt template.

    Uses explicit string replacement instead of str.format() to prevent
    KeyError/IndexError when a user-supplied expert field happens to contain
    literal brace characters (e.g. a role title like "Lead {DevOps} Engineer").
    The prompt template must use the placeholder tokens listed below.
    """
    template = load_prompt("interview_system.txt")
    return (
        template
        .replace("{expert_name}", expert.get("name", "Unknown"))
        .replace("{expert_role}", expert.get("role", "Unknown Role"))
        .replace("{expert_department}", expert.get("department", "Unknown Department"))
        .replace("{turn_count}", str(turn_count))
    )


def build_messages(session_id: int) -> list[dict]:
    """Build the Anthropic messages list from the session history in SQLite."""
    rows = db.get_messages(session_id)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def should_extract(turn_count: int) -> bool:
    """Return True when mid-interview extraction should fire."""
    return turn_count > 0 and turn_count % EXTRACTION_INTERVAL == 0


def get_opening_message(expert: dict) -> str:
    """Generate the very first message from the assistant to start an interview."""
    return (
        f"Hello! I'm here to capture your invaluable knowledge and experience. "
        f"I understand you're {expert.get('name', 'an expert')} working as "
        f"{expert.get('role', 'a subject-matter expert')} in {expert.get('department', 'your department')}. "
        f"I'd love to start by understanding the scope of your work. "
        f"What are the two or three most critical areas of knowledge that you think would be hardest for a successor to learn on their own?"
    )

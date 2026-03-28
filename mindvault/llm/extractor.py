"""Knowledge artifact extractor — LLM JSON call → structured artifacts."""
from __future__ import annotations

import json
import re

from mindvault.config import load_prompt
from mindvault.llm.claude_client import chat

# Must stay in sync with ARTIFACT_TYPES in sqlite_db.py and extraction_system.txt.
_VALID_TYPES = {
    "heuristic",
    "if_then_rule",
    "case_example",
    "red_flag",
    "mental_model",
    "exception",
    "decision_factor",
}

# Artifacts with confidence below this threshold trigger a re-probe in the
# interview agent before the session moves on.
LOW_CONFIDENCE_THRESHOLD = 0.7


def extract_artifacts(text: str) -> list[dict]:
    """
    Extract structured knowledge artifacts from free-form text.

    Calls the LLM with the extraction system prompt and expects a JSON array
    response.  Each element should conform to:
        {
            "artifact_type": one of _VALID_TYPES,
            "title": str,
            "content": str (min 30 chars),
            "tags": list[str],
            "confidence": float (0.0–1.0)
        }
    Returns only the elements that pass _valid_artifact() validation.
    """
    if not text or not text.strip():
        return []

    system = load_prompt("extraction_system.txt")
    messages = [{"role": "user", "content": f"Extract all knowledge artifacts from the following text:\n\n{text}"}]

    raw = chat(messages, system=system, max_tokens=4096)
    return _parse_json_response(raw)


def get_low_confidence_mental_models(artifacts: list[dict]) -> list[dict]:
    """
    Filter the artifact list for mental_model entries whose confidence is
    below LOW_CONFIDENCE_THRESHOLD.

    Called after each mid-interview extraction pass to decide whether the
    interview agent should inject a re-probe instruction on the next turn.
    """
    return [
        a for a in artifacts
        if a.get("artifact_type") == "mental_model"
        and float(a.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD
    ]


def analyse_document(text: str) -> dict:
    """
    Run resource-analysis (summary + gap identification) on a document.
    Returns {summary: str, gaps: list[dict]}.
    """
    if not text or not text.strip():
        return {"summary": "", "gaps": []}

    system = load_prompt("resource_analysis.txt")
    messages = [{"role": "user", "content": f"Analyse the following document:\n\n{text}"}]

    raw = chat(messages, system=system, max_tokens=4096)

    # Strip markdown fences if present
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        result = json.loads(clean)
        return {
            "summary": result.get("summary", ""),
            "gaps": result.get("gaps", []),
        }
    except json.JSONDecodeError:
        return {"summary": raw[:500], "gaps": []}


def _parse_json_response(raw: str) -> list[dict]:
    """
    Parse the LLM's JSON response, stripping Markdown code fences if present.

    LLMs commonly wrap JSON output in ```json ... ``` fences even when
    instructed not to.  The regex strips leading and trailing fence lines so
    json.loads() can parse the payload directly.
    """
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(clean)
        if not isinstance(data, list):
            return []
        return [a for a in data if _valid_artifact(a)]
    except json.JSONDecodeError:
        return []


def _valid_artifact(a: dict) -> bool:
    """
    Return True only if the artifact dict has the required fields and types.

    The 30-character minimum on content filters out placeholder or
    degenerate extractions that provide no useful knowledge signal.
    confidence is optional in the response; it defaults to 1.0 if absent.
    """
    return (
        isinstance(a, dict)
        and a.get("artifact_type") in _VALID_TYPES
        and isinstance(a.get("title"), str)
        and len(a.get("title", "")) > 0
        and isinstance(a.get("content"), str)
        and len(a.get("content", "")) >= 30
    )

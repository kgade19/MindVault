"""
Consistency checker — detects contradictions and conflicts across an expert's artifacts.

Called once after a session is marked complete.  It fetches all of the expert's
extracted artifacts, sends them to Claude with a structured prompt, and stores
any detected conflicts in the artifact_conflicts table.

Conflicts are cleared and re-computed each time it runs so the results always
reflect the current full artifact set (not cumulative noise).
"""
from __future__ import annotations

import json
import re

from mindvault.config import load_prompt
from mindvault.database import sqlite_db as db
from mindvault.llm.claude_client import chat


def run_for_expert(expert_id: int) -> list[dict]:
    """
    Run a full consistency check across all artifacts extracted for this expert.

    Steps:
    1. Load all artifacts for the expert.
    2. If fewer than two artifacts exist, there is nothing to compare — return [].
    3. Build a numbered list of artifacts for the prompt.
    4. Call Claude with the consistency check system prompt.
    5. Parse the JSON response into a list of conflict dicts.
    6. Clear any prior conflicts for this expert (re-compute from scratch).
    7. Persist new conflicts and return the list.
    """
    artifacts = db.get_artifacts(expert_id=expert_id)
    if len(artifacts) < 2:
        return []

    # Build a compact numbered list the LLM can reference by number
    artifact_lines = []
    for i, a in enumerate(artifacts, start=1):
        artifact_lines.append(
            f"[{i}] ({a['artifact_type']}) {a['title']}: {a['content'][:300]}"
        )
    artifact_block = "\n\n".join(artifact_lines)

    system = load_prompt("consistency_check.txt")
    user_msg = (
        f"Analyse the following {len(artifacts)} knowledge artifacts extracted from "
        f"interviews with the same expert and identify any conflicts or contradictions.\n\n"
        f"{artifact_block}"
    )

    raw = chat([{"role": "user", "content": user_msg}], system=system, max_tokens=4096)
    conflicts = _parse_conflicts(raw)

    # Replace previous results for this expert so the check is idempotent
    db.delete_artifact_conflicts_for_expert(expert_id)

    saved = []
    for c in conflicts:
        idx_a = c.get("artifact_index_a")
        idx_b = c.get("artifact_index_b")
        conflict_type = c.get("conflict_type", "contradiction")
        description = c.get("description", "")

        # artifact_index_a/b are 1-based indices into the artifacts list we built
        if not _valid_indices(idx_a, idx_b, len(artifacts)):
            continue

        artifact_a = artifacts[idx_a - 1]
        artifact_b = artifacts[idx_b - 1]

        db.create_artifact_conflict(
            artifact_id_a=artifact_a["id"],
            artifact_id_b=artifact_b["id"],
            conflict_type=conflict_type,
            description=description,
        )
        saved.append({
            "artifact_a": artifact_a["title"],
            "artifact_b": artifact_b["title"],
            "conflict_type": conflict_type,
            "description": description,
        })

    return saved


def _parse_conflicts(raw: str) -> list[dict]:
    """
    Parse the LLM's JSON response.  Strip Markdown code fences if present,
    then JSON-decode the array.  Returns [] on any parse failure.
    """
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(clean)
        if not isinstance(data, list):
            return []
        return data
    except json.JSONDecodeError:
        return []


def _valid_indices(idx_a: object, idx_b: object, count: int) -> bool:
    """Return True only when both indices are valid 1-based positions."""
    return (
        isinstance(idx_a, int)
        and isinstance(idx_b, int)
        and 1 <= idx_a <= count
        and 1 <= idx_b <= count
        and idx_a != idx_b
    )

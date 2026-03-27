"""RAG retriever — vector search + LLM synthesis + conflict detection."""
from __future__ import annotations

from mindvault.config import load_prompt
from mindvault.database import chroma_db
from mindvault.llm.claude_client import chat

_N_RESULTS = 8


def retrieve_and_synthesize(
    query: str,
    expert_id: int | None = None,
    artifact_type: str | None = None,
) -> dict:
    """
    Full RAG pipeline:
    1. Build ChromaDB where-filter from optional expert_id / artifact_type.
    2. Query both collections and merge top-N results.
    3. Call Claude to synthesize a cited answer.
    4. Parse conflicts from the response.
    Returns: {answer, sources, conflicts, raw_chunks}
    """
    where = _build_where(expert_id, artifact_type)

    hits = chroma_db.query_all(query, n_results=_N_RESULTS, where=where)

    if not hits:
        return {
            "answer": "No relevant knowledge found in the knowledge base for this query.",
            "sources": [],
            "conflicts": [],
            "raw_chunks": [],
        }

    context_blocks = _format_chunks(hits)
    system = load_prompt("query_system.txt")
    user_message = (
        f"Question: {query}\n\n"
        f"Retrieved Knowledge Chunks:\n\n{context_blocks}"
    )

    response_text = chat(
        messages=[{"role": "user", "content": user_message}],
        system=system,
        max_tokens=3000,
    )

    answer, conflicts = _parse_response(response_text)

    sources = [
        {
            "source_ref": h["metadata"].get("source_ref", "Unknown"),
            "source_type": h["metadata"].get("source_type", ""),
            "artifact_type": h["metadata"].get("artifact_type", ""),
            "snippet": h["document"][:200],
        }
        for h in hits
    ]

    return {
        "answer": answer,
        "sources": sources,
        "conflicts": conflicts,
        "raw_chunks": hits,
    }


def _build_where(expert_id: int | None, artifact_type: str | None) -> dict | None:
    """
    Build a ChromaDB metadata filter for optional expert and type constraints.

    ChromaDB requires a specific filter structure:
    - A single condition is passed directly as {field: {operator: value}}.
    - Multiple conditions must be wrapped in {"$and": [condition, ...]}.
      Omitting the $and wrapper when >1 condition is present raises a
      ChromaDB validation error.

    Metadata values in ChromaDB are stored as strings (see chroma_db._sanitise_metadata),
    so expert_id is compared as a string even though it is an integer in SQLite.
    """
    conditions = []
    if expert_id is not None:
        conditions.append({"expert_id": {"$eq": str(expert_id)}})
    if artifact_type:
        conditions.append({"artifact_type": {"$eq": artifact_type}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _format_chunks(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        meta = h["metadata"]
        ref = meta.get("source_ref", "Unknown")
        a_type = meta.get("artifact_type", "")
        label = f"[Source {i}] {ref}" + (f" ({a_type})" if a_type else "")
        parts.append(f"{label}\n{h['document']}")
    return "\n\n---\n\n".join(parts)


def _parse_response(text: str) -> tuple[str, list[str]]:
    """
    Split the LLM response into an answer body and a list of conflict strings.

    The query system prompt instructs the model to append a "**⚠ Conflicts
    Detected:**" section when it finds contradictory statements across sources.
    We split on that exact marker so the UI can render conflicts separately
    from the main answer.
    """
    conflict_marker = "**⚠ Conflicts Detected:**"
    if conflict_marker in text:
        parts = text.split(conflict_marker, 1)
        answer = parts[0].strip()
        conflict_text = parts[1].strip()
        conflicts = [line.lstrip("- •").strip() for line in conflict_text.splitlines() if line.strip()]
    else:
        answer = text.strip()
        conflicts = []
    return answer, conflicts

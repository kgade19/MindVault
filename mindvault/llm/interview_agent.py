"""Interview agent — builds messages, tracks phase, triggers mid-interview extraction."""
from __future__ import annotations

from mindvault.config import EXTRACTION_INTERVAL, load_prompt
from mindvault.database import sqlite_db as db
from mindvault.database import chroma_db
from mindvault.llm import claude_client
from mindvault.llm.extractor import LOW_CONFIDENCE_THRESHOLD

# Cosine distance threshold above which a chunk is considered too dissimilar to
# be useful context.  ChromaDB uses L2-normalised cosine distance in [0, 2];
# values below 1.5 are meaningfully related to the query.
_DISTANCE_THRESHOLD = 1.5


def get_document_context(expert_id: int, query_text: str, session_topic: str = "") -> str:
    """
    Retrieve relevant document excerpts and stored knowledge gaps for the current
    expert turn.  Called once per user message; the result is injected into the
    Claude system prompt so the AI can ask better follow-up questions.

    Token budget: max 4 chunks × 200 chars + max 3 gaps × 100 chars ≈ 500 extra
    tokens per turn — well within a typical 200-token system-prompt headroom.

    Returns a formatted context block, or a "no documents" placeholder string so
    the prompt template placeholder is always cleanly replaced.
    """
    # Query the resource_chunks collection filtered to this expert.
    where_filter: dict = {"expert_id": expert_id}
    try:
        hits = chroma_db.query_chunks(query_text, n_results=8, where=where_filter)
    except Exception:
        hits = []

    # Keep only chunks that are semantically close enough to be useful.
    relevant: list[dict] = []
    for h in hits:
        if h.get("distance", 2.0) >= _DISTANCE_THRESHOLD:
            continue
        # If this session is project-scoped and the chunk carries a project tag
        # that doesn't match, skip it so we stay on-topic.
        if session_topic:
            chunk_project = h.get("metadata", {}).get("project", "")
            if chunk_project and chunk_project != session_topic:
                continue
        relevant.append(h)

    # Sort ascending (closest first) and cap at 4 chunks.
    relevant.sort(key=lambda x: x.get("distance", 2.0))
    relevant = relevant[:4]

    # Pull persisted knowledge gaps for this expert (most recent first, cap at 3).
    gaps = db.get_document_gaps(expert_id=expert_id)[:3]

    if not relevant and not gaps:
        return "No documents have been ingested for this expert yet."

    lines: list[str] = []

    if relevant:
        lines.append("**Relevant excerpts from ingested documents:**")
        for h in relevant:
            source = h.get("metadata", {}).get("source_ref", "Unknown source")
            text = h["document"]
            excerpt = text[:200] + ("…" if len(text) > 200 else "")
            lines.append(f"*Source: {source}*\n{excerpt}")
            lines.append("")

    if gaps:
        lines.append("**Identified knowledge gaps in this expert's documents:**")
        for g in gaps:
            desc = g.get("gap_description", "")
            short_desc = desc[:100] + ("…" if len(desc) > 100 else "")
            lines.append(f"- **{g.get('gap_title', '')}**: {short_desc}")
            qs = g.get("suggested_questions", [])[:2]
            for q in qs:
                lines.append(f"  • {q}")

    lines.append("")
    lines.append(
        "Use these excerpts and gaps as silent background context. "
        "Reference a source by name only when directly relevant. "
        "Do not summarise or lecture from the documents — use this context to "
        "formulate sharper follow-up questions and probe where the expert's "
        "lived experience may differ from or extend what was written."
    )
    return "\n".join(lines)


def get_session_summary(expert_id: int) -> str:
    """
    Generate a short (~200-word) prose summary of the most recent completed session
    for this expert. Used to give the AI context when continuing an interview.

    Returns an empty string if no completed session exists or the session has no messages.
    """
    sessions = db.get_sessions_for_expert(expert_id)
    # Find the most recently completed session
    completed = [s for s in sessions if s.get("status") == "completed"]
    if not completed:
        return ""

    latest = completed[-1]
    messages = db.get_messages(latest["id"])
    if not messages:
        return ""

    # Build a transcript excerpt (last 20 turns to stay within token budget)
    transcript_lines = []
    for m in messages[-20:]:
        role_label = "Interviewer" if m["role"] == "assistant" else "Expert"
        transcript_lines.append(f"{role_label}: {m['content']}")
    transcript = "\n".join(transcript_lines)

    summary_prompt = (
        "The following is an excerpt from a knowledge-capture interview. "
        "Write a concise factual summary (maximum 200 words) of the KEY topics, "
        "decisions, rules, and examples that were covered. Focus on what was learned, "
        "not the conversational mechanics. Use plain prose, no bullet points.\n\n"
        f"{transcript}"
    )
    return claude_client.chat([{"role": "user", "content": summary_prompt}], max_tokens=400)


def _build_reprobe_instruction(artifacts: list[dict]) -> str:
    """
    Build an instruction to inject into the system prompt when low-confidence
    mental_model artifacts were extracted in a previous session. This tells the
    AI to revisit those topics and probe for the missing detail.

    Returns an empty string when there is nothing to re-probe.
    """
    low_conf = [
        a for a in artifacts
        if a.get("artifact_type") == "mental_model"
        and float(a.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD
    ]
    if not low_conf:
        return ""

    titles = "\n".join(f"- {a['title']}" for a in low_conf[:5])
    return (
        "The following mental models were captured in a previous session with low confidence. "
        "At an appropriate point, revisit these topics and ask targeted questions to fill the gaps:\n"
        f"{titles}\n"
        "Do not mention 'confidence' or 'low confidence' to the expert — just probe naturally."
    )


def build_system_prompt(
    expert: dict,
    turn_count: int,
    previous_summary: str = "",
    reprobe_instruction: str = "",
    session_topic: str = "",
    document_context: str = "",
) -> str:
    """
    Load and populate the interview system prompt template.

    Uses explicit string replacement instead of str.format() to prevent
    KeyError/IndexError when a user-supplied expert field happens to contain
    literal brace characters (e.g. a role title like "Lead {DevOps} Engineer").
    """
    template = load_prompt("interview_system.txt")

    # Format the previous summary block — blank line if nothing to show
    if previous_summary:
        summary_block = f"Previous session summary:\n{previous_summary}"
    else:
        summary_block = "This is the first session with this expert."

    if session_topic:
        focus_block = f"This session is focused on the project: **{session_topic}**. Stay anchored to this project throughout. Only broaden to general domain knowledge if the expert explicitly runs out of things to say about this project."
    else:
        focus_block = "No specific project focus for this session — cover broad domain knowledge across all areas."

    doc_block = document_context if document_context else "No documents have been ingested for this expert yet."

    return (
        template
        .replace("{expert_name}", expert.get("name", "Unknown"))
        .replace("{expert_role}", expert.get("role", "Unknown Role"))
        .replace("{expert_department}", expert.get("department", "Unknown Department"))
        .replace("{expert_domain}", expert.get("domain", "their domain"))
        .replace("{expert_tenure_years}", str(expert.get("tenure_years") or "unknown number of"))
        .replace("{expert_key_projects}", expert.get("key_projects") or "not specified")
        .replace("{expert_knowledge_gaps}", expert.get("knowledge_gaps") or "none specified")
        .replace("{expert_departure_urgency}", expert.get("departure_urgency") or "standard")
        .replace("{expert_notes}", expert.get("notes") or "none")
        .replace("{turn_count}", str(turn_count))
        .replace("{session_topic}", focus_block)
        .replace("{previous_summary}", summary_block)
        .replace("{reprobe_instruction}", reprobe_instruction or "No specific re-probe targets for this session.")
        .replace("{document_context}", doc_block)
    )


def build_messages(session_id: int) -> list[dict]:
    """Build the Anthropic messages list from the session history in SQLite."""
    rows = db.get_messages(session_id)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def should_extract(turn_count: int) -> bool:
    """Return True when mid-interview extraction should fire."""
    return turn_count > 0 and turn_count % EXTRACTION_INTERVAL == 0


def get_opening_message(expert: dict, session_topic: str = "") -> str:
    """
    Generate the first message to open Phase 1.

    When a specific project is selected, the opening is anchored to that project
    so the expert doesn't have to re-orient. Without a project, falls back to
    the domain-mapping framing (what juniors get wrong).
    """
    name = expert.get("name", "")
    greeting = f"Hello{', ' + name if name else ''}!"
    if session_topic:
        return (
            f"{greeting} For this session I'd like to focus on **{session_topic}**. "
            f"Before we go into the details — can you walk me through your role in that project: "
            f"what you personally owned, what the main challenges were, "
            f"and what you'd tell someone starting fresh on it today?"
        )
    domain = expert.get("domain") or expert.get("role", "your field")
    return (
        f"{greeting} I'm here to capture your knowledge and experience before you move on. "
        f"I want to start broadly before we go deep. "
        f"In {domain}, what do junior or less experienced people consistently get wrong "
        f"that takes years of hands-on work to really understand?"
    )

"""Shared ingest pipeline — used by both the Ingest page and mid-interview uploads.

All Streamlit UI logic lives in the calling page; this module is pure Python so
it can be called from any context (page, background job, test).
"""
from __future__ import annotations

from mindvault.database import sqlite_db as db
from mindvault.llm import extractor
from mindvault.rag import embedder


def run_pipeline(
    expert_id: int,
    source_type: str,
    source_ref: str,
    title: str,
    content_text: str,
    sha256: str = "",
    project: str = "",
) -> dict:
    """
    Run the full ingest pipeline for a single document.

    Steps:
      1. Dedup check via sha256 — returns early if the content was already ingested.
      2. Persist document row to SQLite.
      3. Chunk text and upsert chunks into ChromaDB resource_chunks collection.
      4. Extract knowledge artifacts → save to SQLite + embed into artifacts collection.
      5. Analyse document for knowledge gaps → persist to document_gaps table.

    Returns a dict with:
      skipped          (bool)       True when the sha256 matched an existing document.
      existing         (dict|None)  The existing document row when skipped, else None.
      doc_id           (int|None)   The new document's SQLite row ID, or None if skipped.
      n_chunks         (int)        Number of text chunks embedded.
      artifacts        (list[dict]) Extracted knowledge artifacts.
      gaps             (list[dict]) Extracted knowledge gaps.
      analysis_summary (str)        Short prose summary from the gap-analysis prompt.
    """
    # 1. Dedup — skip if we have already ingested this exact content.
    if sha256:
        existing = db.sha256_exists(sha256)
        if existing:
            return {
                "skipped": True,
                "existing": dict(existing),
                "doc_id": None,
                "n_chunks": 0,
                "artifacts": [],
                "gaps": [],
                "analysis_summary": "",
            }

    # 2. Persist document.
    doc_id = db.create_document(
        expert_id=expert_id,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        content_text=content_text,
        sha256=sha256,
        project=project,
    )

    # 3. Embed text chunks (project stored in metadata for per-project filtering).
    n_chunks = embedder.embed_and_store(
        content_text,
        source_type=source_type,
        source_ref=source_ref,
        expert_id=expert_id,
        document_id=doc_id,
        project=project,
    )

    # 4. Extract structured knowledge artifacts from the document text.
    artifacts = extractor.extract_artifacts(content_text)
    for art in artifacts:
        art_id = db.create_artifact(
            artifact_type=art["artifact_type"],
            title=art["title"],
            content=art["content"],
            tags=art.get("tags", []),
            expert_id=expert_id,
            document_id=doc_id,
            confidence=float(art.get("confidence", 1.0)),
        )
        embedder.embed_artifact(
            art_id, art["title"], art["content"],
            art["artifact_type"], expert_id, source_ref,
        )

    # 5. Gap analysis — identify what questions the document raises but doesn't answer.
    analysis = extractor.analyse_document(content_text)
    gaps = analysis.get("gaps", [])
    for gap in gaps:
        db.create_document_gap(
            document_id=doc_id,
            gap_title=gap.get("gap_title", ""),
            gap_description=gap.get("gap_description", ""),
            questions=gap.get("suggested_interview_questions", []),
        )

    return {
        "skipped": False,
        "existing": None,
        "doc_id": doc_id,
        "n_chunks": n_chunks,
        "artifacts": artifacts,
        "gaps": gaps,
        "analysis_summary": analysis.get("summary", ""),
    }

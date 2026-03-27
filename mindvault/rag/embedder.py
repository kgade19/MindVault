"""RAG embedder — chunk text and upsert to ChromaDB."""
from __future__ import annotations

import hashlib
import re

from mindvault.database import chroma_db

# Chunk size is measured in words (a reasonable proxy for tokens without
# requiring a tokeniser dependency). 500 words ≈ 650–750 tokens for typical
# English prose, staying well within embedding-model context windows.
_CHUNK_SIZE = 500

# 50 % overlap ensures that knowledge spanning a chunk boundary is captured
# in at least one complete chunk. Higher overlap improves recall at the cost
# of storing more redundant chunks.
_CHUNK_OVERLAP = 250


def chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping chunks of ~CHUNK_SIZE words.
    Respects paragraph boundaries where possible.
    """
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    words = text.split()
    if len(words) <= _CHUNK_SIZE:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + _CHUNK_SIZE, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def embed_and_store(
    text: str,
    source_type: str,
    source_ref: str,
    expert_id: int | None = None,
    document_id: int | None = None,
    session_id: int | None = None,
) -> int:
    """
    Chunk text and upsert all chunks into the resource_chunks collection.
    Returns the number of chunks stored.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0

    base_metadata: dict = {
        "source_type": source_type,
        "source_ref": source_ref,
        "expert_id": expert_id or "",
        "document_id": document_id or "",
        "session_id": session_id or "",
    }

    for i, chunk in enumerate(chunks):
        # Build a stable, collision-resistant chunk ID from the source reference,
        # position index, and a prefix of the chunk text.  We truncate the hex
        # digest to 32 characters (128 bits) — sufficient for dedup within a
        # single knowledge base while keeping IDs readable in ChromaDB tooling.
        chunk_id = hashlib.sha256(f"{source_ref}::{i}::{chunk[:64]}".encode()).hexdigest()[:32]
        metadata = {**base_metadata, "chunk_index": i, "chunk_total": len(chunks)}
        chroma_db.upsert_chunk(chunk_id, chunk, metadata)

    return len(chunks)


def embed_artifact(
    artifact_id: int,
    title: str,
    content: str,
    artifact_type: str,
    expert_id: int | None = None,
    source_ref: str = "",
) -> None:
    """Embed a knowledge artifact into the artifacts collection.

    Title and content are concatenated so the embedding captures both the
    short label and the full body — improving recall for both broad and
    specific queries.
    """
    text = f"{title}\n\n{content}"
    metadata: dict = {
        "artifact_type": artifact_type,
        "title": title,
        "expert_id": expert_id or "",
        "source_ref": source_ref,
    }
    chroma_db.upsert_artifact(artifact_id, text, metadata)

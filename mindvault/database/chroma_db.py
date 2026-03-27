"""ChromaDB wrapper — two collections: artifacts and resource_chunks."""
from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

from mindvault.config import CHROMA_DIR

# Collection names
ARTIFACTS_COLLECTION = "artifacts"
CHUNKS_COLLECTION = "resource_chunks"

# Module-level lazy singleton: ChromaDB starts an embedded DuckDB-backed process
# on first access.  Reusing one client per process avoids the overhead of
# re-opening the database file on every call.
_client: chromadb.PersistentClient | None = None

# DefaultEmbeddingFunction uses the all-MiniLM-L6-v2 sentence-transformer model
# (downloaded on first use, ~80 MB).  All collections share one instance so the
# model is loaded into memory only once.
_ef = embedding_functions.DefaultEmbeddingFunction()


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_artifacts_collection() -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=ARTIFACTS_COLLECTION, embedding_function=_ef
    )


def get_chunks_collection() -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=CHUNKS_COLLECTION, embedding_function=_ef
    )


def upsert_artifact(
    artifact_id: int,
    text: str,
    metadata: dict,
) -> None:
    """Embed and upsert a knowledge artifact into the artifacts collection."""
    col = get_artifacts_collection()
    col.upsert(
        ids=[f"artifact-{artifact_id}"],
        documents=[text],
        metadatas=[_sanitise_metadata(metadata)],
    )


def upsert_chunk(
    chunk_id: str,
    text: str,
    metadata: dict,
) -> None:
    """Embed and upsert a raw text chunk into the resource_chunks collection."""
    col = get_chunks_collection()
    col.upsert(
        ids=[chunk_id],
        documents=[text],
        metadatas=[_sanitise_metadata(metadata)],
    )


def query_artifacts(
    query_text: str,
    n_results: int = 8,
    where: dict | None = None,
) -> list[dict]:
    col = get_artifacts_collection()
    kwargs: dict = {"query_texts": [query_text], "n_results": min(n_results, col.count() or 1)}
    if where:
        kwargs["where"] = where
    results = col.query(**kwargs)
    return _format_results(results)


def query_chunks(
    query_text: str,
    n_results: int = 8,
    where: dict | None = None,
) -> list[dict]:
    col = get_chunks_collection()
    kwargs: dict = {"query_texts": [query_text], "n_results": min(n_results, col.count() or 1)}
    if where:
        kwargs["where"] = where
    results = col.query(**kwargs)
    return _format_results(results)


def query_all(
    query_text: str,
    n_results: int = 8,
    where: dict | None = None,
) -> list[dict]:
    """Query both collections and merge results, ranked by distance."""
    artifact_hits = query_artifacts(query_text, n_results, where)
    chunk_hits = query_chunks(query_text, n_results, where)
    combined = artifact_hits + chunk_hits
    combined.sort(key=lambda x: x.get("distance", 1.0))
    return combined[:n_results]


def _format_results(results: dict) -> list[dict]:
    hits = []
    if not results or not results.get("ids"):
        return hits
    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results.get("distances", [[]])[0]
    for i, doc_id in enumerate(ids):
        hits.append(
            {
                "id": doc_id,
                "document": docs[i],
                "metadata": metas[i],
                "distance": distances[i] if distances else None,
            }
        )
    return hits


def _sanitise_metadata(metadata: dict) -> dict:
    """ChromaDB only accepts str/int/float/bool metadata values."""
    clean = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif v is None:
            clean[k] = ""
        else:
            clean[k] = str(v)
    return clean

# MindVault — Project Guidelines

MindVault is a **knowledge preservation platform**: AI-guided interviews with subject-matter experts, multi-source ingestion, structured artifact extraction, and RAG-based querying. Built with Streamlit + Claude + ChromaDB + SQLite.

## Build and Run

```bash
# First time
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # set ANTHROPIC_API_KEY=sk-ant-...

# Run
streamlit run app.py        # http://localhost:8501
```

**System prerequisite:** `ffmpeg` on PATH (required for non-WAV audio transcription via faster-whisper).  
**No test suite exists.** Manual verification through the Streamlit UI is the current workflow.

## Architecture

```
app.py + pages/          → Streamlit multi-page UI (5 pages)
mindvault/llm/           → All Claude calls (streaming, vision, extraction, interview)
mindvault/ingestion/     → PDF / URL / image / audio → raw text
mindvault/rag/           → Chunk → embed → ChromaDB upsert; semantic retrieval + synthesis
mindvault/database/      → SQLite (relational) + ChromaDB (vector) wrappers
mindvault/voice/         → STT (faster-whisper) + TTS (gTTS)
prompts/                 → System prompt .txt files, never hardcoded in Python
```

**Data flow — Interview:** user turn → `interview_agent` → `claude_client.stream_chat` → every 3 turns `extractor.extract_artifacts` fires → artifacts → SQLite + ChromaDB `artifacts` collection.  
**Data flow — Ingest:** file/URL → parser → `extractor` (structured) + `embedder` (chunks) → ChromaDB `resource_chunks` collection.  
**Data flow — Query:** query → `retriever.retrieve_and_synthesize` → both ChromaDB collections → Claude cited answer with conflict detection.

ChromaDB uses two collections: `artifacts` and `resource_chunks`. Embeddings use the local default (`all-MiniLM-L6-v2`) — no external embedding API.

SQLite schema: `experts` → `interview_sessions` → `interview_messages`, `documents`, `knowledge_artifacts`. All data stored locally under `data/`.

## Configuration

All config lives in `.env` (loaded by `mindvault/config.py`):

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** — hard crash on missing |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | |
| `WHISPER_MODEL_SIZE` | `base` | Only used when `STT_PROVIDER=faster_whisper` |
| `STT_PROVIDER` | `groq` | `groq` (recommended) or `faster_whisper` (local, needs ffmpeg) |
| `GROQ_API_KEY` | — | Required when `STT_PROVIDER=groq` — free at console.groq.com |
| `EXTRACTION_INTERVAL` | `3` | Mid-interview artifact extraction every N user turns |
| `DATA_DIR` | `data` | SQLite, ChromaDB, uploads root |

`config.py` auto-creates `data/`, `data/chroma/`, `data/uploads/` at import time and exposes `load_prompt(filename)` for reading from `prompts/`.

## Conventions

- **snake_case** for all files, folders, functions, and variables.
- Module-level **lazy singletons** for expensive resources (Anthropic client, ChromaDB client, Whisper model) — use `global _var` pattern, initialized on first use.
- **Absolute imports**: `from mindvault.database import sqlite_db as db`.
- `__init__.py` files are empty — no re-export aggregation.
- **Type hints** throughout; `from __future__ import annotations` in most modules.
- **SQLite access** via the `@contextmanager _conn()` helper in `sqlite_db.py` — never bypass it.
- **Prompts** live in `prompts/*.txt`, loaded via `config.load_prompt()` — never hardcode system prompts in Python.
- Pages call `init_db()` defensively on load (it is idempotent).
- ChromaDB metadata must be sanitized (no `None` values) before upsert — see `chroma_db.py` for the pattern.
- Valid artifact types (SQLite CHECK constraint): `decision`, `lesson_learned`, `process`, `named_entity`, `open_question`. Use `extractor._valid_artifact()` before inserts.

## Key Files

| File | Purpose |
|---|---|
| `mindvault/config.py` | All env vars, paths, `load_prompt()` |
| `mindvault/database/sqlite_db.py` | Full schema DDL + all CRUD helpers |
| `mindvault/database/chroma_db.py` | ChromaDB wrapper for both collections |
| `mindvault/llm/claude_client.py` | All Claude calls (streaming, non-streaming, vision) |
| `mindvault/llm/extractor.py` | Artifact extraction and document gap analysis |
| `mindvault/rag/embedder.py` | Chunking (500-word, 250-word overlap) + ChromaDB upsert |
| `mindvault/rag/retriever.py` | Full RAG pipeline: query → retrieve → synthesize → parse conflicts |
| `pages/1_Interview.py` | Most complex page; full interview + mid-turn extraction loop |

## Pitfalls

- **Missing `.env`** → hard crash at import. Ensure `ANTHROPIC_API_KEY` is set before running.
- **Voice I/O (STT)** — default provider is `groq` (cloud, free, no DLLs). Set `STT_PROVIDER=faster_whisper` to use local Whisper, but it requires ffmpeg and is blocked by Windows Smart App Control on some machines.
- **Whisper model download on first local STT use** — downloads ~150 MB silently; not a hang.
- **No authentication** — single-user local app; do not expose the Streamlit port publicly.
- **gTTS requires internet** — TTS fails in air-gapped environments; limited to 3000 chars/call.
- **ChromaDB `n_results` guard** — always use the `chroma_db.py` wrapper (not the raw collection) to avoid `n_results > collection size` errors.

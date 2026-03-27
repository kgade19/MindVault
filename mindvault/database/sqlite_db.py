"""SQLite database — schema init and CRUD helpers."""
import json
import sqlite3
from contextlib import contextmanager
from typing import Generator

from mindvault.config import DB_PATH

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS experts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT '',
    department  TEXT    NOT NULL DEFAULT '',
    notes       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS interview_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id    INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    started_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    completed_at TEXT,
    status       TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed'))
);

CREATE TABLE IF NOT EXISTS interview_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    content    TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id    INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    source_type  TEXT    NOT NULL CHECK(source_type IN ('pdf','url','text','image','audio')),
    source_ref   TEXT    NOT NULL DEFAULT '',
    title        TEXT    NOT NULL DEFAULT '',
    content_text TEXT    NOT NULL DEFAULT '',
    sha256       TEXT    NOT NULL DEFAULT '',
    ingested_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS knowledge_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id     INTEGER REFERENCES experts(id) ON DELETE SET NULL,
    document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    session_id    INTEGER REFERENCES interview_sessions(id) ON DELETE SET NULL,
    artifact_type TEXT    NOT NULL CHECK(artifact_type IN ('decision','lesson_learned','process','named_entity','open_question')),
    title         TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE INDEX IF NOT EXISTS idx_artifacts_expert   ON knowledge_artifacts(expert_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type     ON knowledge_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_messages_session   ON interview_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_docs_sha256        ON documents(sha256);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a short-lived, auto-committing SQLite connection.

    A new physical connection is opened for every call so that each request is
    fully isolated. WAL mode (set in _DDL) allows concurrent readers while a
    write is in progress, which matters when Streamlit reruns overlap.

    check_same_thread=False is safe here because the connection is never shared
    across threads — it is opened, used, and closed within this context manager.
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables and indexes if they do not exist (idempotent)."""
    with _conn() as conn:
        conn.executescript(_DDL)


# ── Experts ───────────────────────────────────────────────────────────────────

def create_expert(name: str, role: str = "", department: str = "", notes: str = "") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO experts (name, role, department, notes) VALUES (?,?,?,?)",
            (name, role, department, notes),
        )
        return cur.lastrowid


def get_experts() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM experts ORDER BY name")]


def get_expert(expert_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM experts WHERE id=?", (expert_id,)).fetchone()
        return dict(row) if row else None


def update_expert(expert_id: int, name: str, role: str, department: str, notes: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE experts SET name=?, role=?, department=?, notes=? WHERE id=?",
            (name, role, department, notes, expert_id),
        )


def delete_expert(expert_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM experts WHERE id=?", (expert_id,))


# ── Interview Sessions ────────────────────────────────────────────────────────

def create_session(expert_id: int) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO interview_sessions (expert_id) VALUES (?)", (expert_id,)
        )
        return cur.lastrowid


def get_active_session(expert_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE expert_id=? AND status='active' ORDER BY started_at DESC LIMIT 1",
            (expert_id,),
        ).fetchone()
        return dict(row) if row else None


def get_sessions_for_expert(expert_id: int) -> list[dict]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM interview_sessions WHERE expert_id=? ORDER BY started_at DESC",
                (expert_id,),
            )
        ]


def complete_session(session_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE interview_sessions SET status='completed', completed_at=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id=?",
            (session_id,),
        )


# ── Messages ──────────────────────────────────────────────────────────────────

def append_message(session_id: int, role: str, content: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO interview_messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, role, content),
        )
        return cur.lastrowid


def get_messages(session_id: int) -> list[dict]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM interview_messages WHERE session_id=? ORDER BY timestamp",
                (session_id,),
            )
        ]


def count_messages(session_id: int) -> int:
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM interview_messages WHERE session_id=?", (session_id,)
        ).fetchone()[0]


# ── Documents ─────────────────────────────────────────────────────────────────

def sha256_exists(sha256: str) -> dict | None:
    """Return existing document if this SHA256 was already ingested."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE sha256=?", (sha256,)).fetchone()
        return dict(row) if row else None


def create_document(
    expert_id: int,
    source_type: str,
    source_ref: str,
    title: str,
    content_text: str,
    sha256: str = "",
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (expert_id, source_type, source_ref, title, content_text, sha256) VALUES (?,?,?,?,?,?)",
            (expert_id, source_type, source_ref, title, content_text, sha256),
        )
        return cur.lastrowid


def get_documents(expert_id: int | None = None) -> list[dict]:
    with _conn() as conn:
        if expert_id is not None:
            rows = conn.execute(
                "SELECT * FROM documents WHERE expert_id=? ORDER BY ingested_at DESC", (expert_id,)
            )
        else:
            rows = conn.execute("SELECT * FROM documents ORDER BY ingested_at DESC")
        return [dict(r) for r in rows]


# ── Knowledge Artifacts ───────────────────────────────────────────────────────

def create_artifact(
    artifact_type: str,
    title: str,
    content: str,
    tags: list[str],
    expert_id: int | None = None,
    document_id: int | None = None,
    session_id: int | None = None,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO knowledge_artifacts
               (expert_id, document_id, session_id, artifact_type, title, content, tags)
               VALUES (?,?,?,?,?,?,?)""",
            (expert_id, document_id, session_id, artifact_type, title, content, json.dumps(tags)),
        )
        return cur.lastrowid


def get_artifacts(
    expert_id: int | None = None,
    artifact_type: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Return knowledge artifacts filtered by optional expert and/or type.

    The WHERE clause is constructed by appending only safe, hard-coded column
    names to the query string; all user-supplied values are bound via the
    parameterised query placeholder list (params).  This avoids SQL injection
    while still allowing a variable number of filter conditions.
    """
    clauses, params = [], []
    if expert_id is not None:
        clauses.append("expert_id=?")
        params.append(expert_id)
    if artifact_type:
        clauses.append("artifact_type=?")
        params.append(artifact_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM knowledge_artifacts {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        results = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            results.append(d)
        return results


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict[str, int]:
    with _conn() as conn:
        return {
            "experts": conn.execute("SELECT COUNT(*) FROM experts").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM interview_sessions").fetchone()[0],
            "artifacts": conn.execute("SELECT COUNT(*) FROM knowledge_artifacts").fetchone()[0],
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        }

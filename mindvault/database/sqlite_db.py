"""SQLite database — schema init and CRUD helpers."""
import json
import sqlite3
from contextlib import contextmanager
from typing import Generator

from mindvault.config import DB_PATH

# The 7 artifact types used by the extraction pipeline.
# Changing this set requires a corresponding migration in _migrate_artifact_type_constraint().
ARTIFACT_TYPES = (
    "heuristic",       # reusable rule of thumb extracted from experience
    "if_then_rule",    # conditional logic: "IF X THEN Y"
    "case_example",    # concrete narrative instance demonstrating a rule
    "red_flag",        # signal + escalation trigger: "when you see X, stop"
    "mental_model",    # how the expert frames a problem domain
    "exception",       # known deviation from a rule: "applies except when..."
    "decision_factor", # recurring variable the expert always weighs before deciding
)

# Comma-separated quoted list used inside the CHECK(...) expression in DDL.
_ARTIFACT_TYPES_SQL = ", ".join(f"'{t}'" for t in ARTIFACT_TYPES)

# DDL for a fresh database installation.  Migrations for existing databases are
# handled separately in init_db() so that this string always reflects the
# desired target schema.
_DDL = f"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS experts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    role              TEXT    NOT NULL DEFAULT '',
    department        TEXT    NOT NULL DEFAULT '',
    notes             TEXT    NOT NULL DEFAULT '',
    domain            TEXT    NOT NULL DEFAULT '',
    tenure_years      INTEGER NOT NULL DEFAULT 0,
    key_projects      TEXT    NOT NULL DEFAULT '',
    knowledge_gaps    TEXT    NOT NULL DEFAULT '',
    departure_urgency TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS interview_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id    INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    topic        TEXT    NOT NULL DEFAULT '',
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
    project      TEXT    NOT NULL DEFAULT '',
    ingested_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS document_gaps (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id          INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    gap_title            TEXT    NOT NULL DEFAULT '',
    gap_description      TEXT    NOT NULL DEFAULT '',
    suggested_questions  TEXT    NOT NULL DEFAULT '[]',
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS knowledge_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id     INTEGER REFERENCES experts(id) ON DELETE SET NULL,
    document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    session_id    INTEGER REFERENCES interview_sessions(id) ON DELETE SET NULL,
    artifact_type TEXT    NOT NULL CHECK(artifact_type IN ({_ARTIFACT_TYPES_SQL})),
    title         TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    confidence    REAL    NOT NULL DEFAULT 1.0,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS artifact_conflicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id_a INTEGER NOT NULL REFERENCES knowledge_artifacts(id) ON DELETE CASCADE,
    artifact_id_b INTEGER NOT NULL REFERENCES knowledge_artifacts(id) ON DELETE CASCADE,
    conflict_type TEXT    NOT NULL DEFAULT '',
    description   TEXT    NOT NULL DEFAULT '',
    detected_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE INDEX IF NOT EXISTS idx_artifacts_expert    ON knowledge_artifacts(expert_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type      ON knowledge_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_messages_session    ON interview_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_docs_sha256         ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_conflicts_artifact  ON artifact_conflicts(artifact_id_a);
CREATE INDEX IF NOT EXISTS idx_gaps_document       ON document_gaps(document_id);
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
    """
    Create all tables and indexes (idempotent for new databases), then run
    incremental migrations for existing databases.

    Migration strategy:
    - Simple column additions use ALTER TABLE wrapped in try/except; SQLite
      raises OperationalError if the column already exists, which we ignore.
    - The knowledge_artifacts CHECK constraint change (5 old types → 7 new)
      requires a full table recreation because SQLite does not support
      ALTER COLUMN.  _migrate_artifact_type_constraint() handles this safely.
    """
    with _conn() as conn:
        conn.executescript(_DDL)

    # ── Column additions (idempotent via try/except) ──────────────────────────
    _add_column_if_missing("experts", "domain",            "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("experts", "tenure_years",      "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("experts", "key_projects",      "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("experts", "knowledge_gaps",    "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("experts", "departure_urgency", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("interview_sessions", "topic",  "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("knowledge_artifacts", "confidence", "REAL NOT NULL DEFAULT 1.0")
    _add_column_if_missing("documents", "project",         "TEXT NOT NULL DEFAULT ''")

    # ── CHECK constraint migration ────────────────────────────────────────────
    # Recreates knowledge_artifacts with the new 7-type constraint only when
    # the existing table still carries the old 5-type constraint.
    _migrate_artifact_type_constraint()


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    """
    Add a column to a table if it does not already exist.

    SQLite raises OperationalError("duplicate column name: ...") when you
    ALTER TABLE ADD COLUMN on an existing column, so we catch and ignore it.
    Any other error is re-raised.
    """
    with _conn() as conn:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def _migrate_artifact_type_constraint() -> None:
    """
    Recreate knowledge_artifacts with the 7-type CHECK constraint.

    SQLite does not support ALTER COLUMN so the only way to change a CHECK
    constraint is to:
      1. Create a new table with the desired schema.
      2. Copy all existing rows, converting old type names to their closest
         new equivalents (best-effort; listed in _LEGACY_TYPE_MAP).
      3. Drop the old table.
      4. Rename the new table.

    This function is a no-op when the constraint is already up to date,
    detected by inspecting the table's CREATE statement in sqlite_master.
    """
    # Best-effort mapping from the old 5 types to the new 7 types.
    # Used only during migration of any rows that were stored with old types.
    _LEGACY_TYPE_MAP = {
        "decision":      "case_example",    # one-off past decision → concrete narrative
        "lesson_learned":"red_flag",         # hard-won warning → signal to watch for
        "process":       "if_then_rule",     # workflow → conditional rule
        "named_entity":  "heuristic",        # entity knowledge → rule of thumb
        "open_question": "exception",        # unresolved issue → exception to normal rule
    }

    with _conn() as conn:
        # Read the current CREATE statement for knowledge_artifacts.
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='knowledge_artifacts'"
        ).fetchone()
        if row is None:
            return  # table does not exist yet; _DDL will create it fresh

        current_sql: str = row[0] or ""

        # If the old 5-type list is still in the constraint, migration is needed.
        if "'open_question'" not in current_sql:
            return  # already migrated

        # Temporarily disable FK enforcement so we can rename without cascade issues.
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS knowledge_artifacts_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                expert_id     INTEGER REFERENCES experts(id) ON DELETE SET NULL,
                document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                session_id    INTEGER REFERENCES interview_sessions(id) ON DELETE SET NULL,
                artifact_type TEXT    NOT NULL CHECK(artifact_type IN ({_ARTIFACT_TYPES_SQL})),
                title         TEXT    NOT NULL,
                content       TEXT    NOT NULL,
                tags          TEXT    NOT NULL DEFAULT '[]',
                confidence    REAL    NOT NULL DEFAULT 1.0,
                created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            )
        """)

        # Copy existing rows, converting legacy type names on the fly using
        # a CASE expression.  Rows with already-valid new types pass through.
        case_expr = "CASE artifact_type\n"
        for old, new in _LEGACY_TYPE_MAP.items():
            case_expr += f"            WHEN '{old}' THEN '{new}'\n"
        case_expr += "            ELSE artifact_type END"

        conn.execute(f"""
            INSERT INTO knowledge_artifacts_new
                (id, expert_id, document_id, session_id, artifact_type,
                 title, content, tags, confidence, created_at)
            SELECT id, expert_id, document_id, session_id,
                   {case_expr},
                   title, content, tags,
                   COALESCE(confidence, 1.0),
                   created_at
            FROM knowledge_artifacts
        """)

        conn.execute("DROP TABLE knowledge_artifacts")
        conn.execute("ALTER TABLE knowledge_artifacts_new RENAME TO knowledge_artifacts")
        conn.execute("PRAGMA foreign_keys=ON")


# ── Experts ───────────────────────────────────────────────────────────────────

def create_expert(
    name: str,
    role: str = "",
    department: str = "",
    notes: str = "",
    domain: str = "",
    tenure_years: int = 0,
    key_projects: str = "",
    knowledge_gaps: str = "",
    departure_urgency: str = "",
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO experts
               (name, role, department, notes, domain, tenure_years,
                key_projects, knowledge_gaps, departure_urgency)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, role, department, notes, domain, tenure_years,
             key_projects, knowledge_gaps, departure_urgency),
        )
        return cur.lastrowid


def get_experts() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM experts ORDER BY name")]


def get_expert(expert_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM experts WHERE id=?", (expert_id,)).fetchone()
        return dict(row) if row else None


def update_expert(
    expert_id: int,
    name: str,
    role: str,
    department: str,
    notes: str,
    domain: str = "",
    tenure_years: int = 0,
    key_projects: str = "",
    knowledge_gaps: str = "",
    departure_urgency: str = "",
) -> None:
    with _conn() as conn:
        conn.execute(
            """UPDATE experts
               SET name=?, role=?, department=?, notes=?,
                   domain=?, tenure_years=?, key_projects=?,
                   knowledge_gaps=?, departure_urgency=?
               WHERE id=?""",
            (name, role, department, notes, domain, tenure_years,
             key_projects, knowledge_gaps, departure_urgency, expert_id),
        )


def delete_expert(expert_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM experts WHERE id=?", (expert_id,))


# ── Interview Sessions ────────────────────────────────────────────────────────

def create_session(expert_id: int, topic: str = "") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO interview_sessions (expert_id, topic) VALUES (?,?)",
            (expert_id, topic),
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


def get_all_session_topics() -> list[str]:
    """Return distinct non-empty session topics across all experts, sorted alphabetically."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM interview_sessions "
            "WHERE topic IS NOT NULL AND topic != '' ORDER BY topic"
        )
        return [r["topic"] for r in rows]


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
    project: str = "",
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (expert_id, source_type, source_ref, title, content_text, sha256, project) VALUES (?,?,?,?,?,?,?)",
            (expert_id, source_type, source_ref, title, content_text, sha256, project),
        )
        return cur.lastrowid


def get_documents(expert_id: int | None = None, project: str | None = None) -> list[dict]:
    with _conn() as conn:
        clauses = []
        params: list = []
        if expert_id is not None:
            clauses.append("expert_id=?")
            params.append(expert_id)
        if project is not None:
            clauses.append("project=?")
            params.append(project)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM documents {where} ORDER BY ingested_at DESC", params
        )
        return [dict(r) for r in rows]


# ── Document Gaps ─────────────────────────────────────────────────────────────

def create_document_gap(
    document_id: int,
    gap_title: str,
    gap_description: str,
    questions: list[str] | None = None,
) -> int:
    """Persist a knowledge gap identified during document analysis."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO document_gaps (document_id, gap_title, gap_description, suggested_questions)
               VALUES (?,?,?,?)""",
            (document_id, gap_title, gap_description, json.dumps(questions or [])),
        )
        return cur.lastrowid


def get_document_gaps(
    document_id: int | None = None,
    expert_id: int | None = None,
) -> list[dict]:
    """
    Return stored document gaps.

    When expert_id is supplied the JOIN to documents is used to filter by expert,
    which is the typical calling pattern for per-turn context injection.
    When document_id is supplied, only gaps for that specific document are returned.
    Both filters can be combined.
    """
    with _conn() as conn:
        if expert_id is not None:
            # Join to documents so we can filter by expert without a subquery.
            clauses = ["d.expert_id=?"]
            params: list = [expert_id]
            if document_id is not None:
                clauses.append("g.document_id=?")
                params.append(document_id)
            where = "WHERE " + " AND ".join(clauses)
            rows = conn.execute(
                f"""SELECT g.*, d.title AS document_title, d.source_ref
                    FROM document_gaps g
                    JOIN documents d ON d.id = g.document_id
                    {where}
                    ORDER BY g.created_at DESC""",
                params,
            )
        elif document_id is not None:
            rows = conn.execute(
                """SELECT g.*, d.title AS document_title, d.source_ref
                   FROM document_gaps g
                   JOIN documents d ON d.id = g.document_id
                   WHERE g.document_id=?
                   ORDER BY g.created_at DESC""",
                (document_id,),
            )
        else:
            rows = conn.execute(
                """SELECT g.*, d.title AS document_title, d.source_ref
                   FROM document_gaps g
                   JOIN documents d ON d.id = g.document_id
                   ORDER BY g.created_at DESC"""
            )
        results = []
        for r in rows:
            row_dict = dict(r)
            # Deserialise the questions JSON list
            try:
                row_dict["suggested_questions"] = json.loads(row_dict.get("suggested_questions", "[]"))
            except (json.JSONDecodeError, TypeError):
                row_dict["suggested_questions"] = []
            results.append(row_dict)
        return results


# ── Knowledge Artifacts ───────────────────────────────────────────────────────

def create_artifact(
    artifact_type: str,
    title: str,
    content: str,
    tags: list[str],
    expert_id: int | None = None,
    document_id: int | None = None,
    session_id: int | None = None,
    confidence: float = 1.0,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO knowledge_artifacts
               (expert_id, document_id, session_id, artifact_type,
                title, content, tags, confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            (expert_id, document_id, session_id, artifact_type,
             title, content, json.dumps(tags), confidence),
        )
        return cur.lastrowid


def get_artifacts(
    expert_id: int | None = None,
    artifact_type: str | None = None,
    project: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Return knowledge artifacts filtered by optional expert, type, and/or project.

    The WHERE clause is constructed by appending only safe, hard-coded column
    names to the query string; all user-supplied values are bound via the
    parameterised query placeholder list (params).  This avoids SQL injection
    while still allowing a variable number of filter conditions.

    project filters by the session topic — it resolves via a subquery on
    interview_sessions so no JOIN is needed on the outer SELECT.
    """
    clauses, params = [], []
    if expert_id is not None:
        clauses.append("expert_id=?")
        params.append(expert_id)
    if artifact_type:
        clauses.append("artifact_type=?")
        params.append(artifact_type)
    if project:
        clauses.append("session_id IN (SELECT id FROM interview_sessions WHERE topic=?)")
        params.append(project)
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
            # confidence may be absent on rows created before the migration
            d.setdefault("confidence", 1.0)
            results.append(d)
        return results


# ── Artifact Conflicts ───────────────────────────────────────────────────────

def create_artifact_conflict(
    artifact_id_a: int,
    artifact_id_b: int,
    conflict_type: str,
    description: str,
) -> int:
    """Record a detected conflict between two artifacts."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO artifact_conflicts
               (artifact_id_a, artifact_id_b, conflict_type, description)
               VALUES (?,?,?,?)""",
            (artifact_id_a, artifact_id_b, conflict_type, description),
        )
        return cur.lastrowid


def get_artifact_conflicts(expert_id: int | None = None) -> list[dict]:
    """
    Return conflicts, optionally filtered to only those where both artifacts
    belong to a specific expert.
    """
    with _conn() as conn:
        if expert_id is not None:
            # Join through knowledge_artifacts to filter by expert.
            rows = conn.execute(
                """SELECT c.*
                   FROM artifact_conflicts c
                   JOIN knowledge_artifacts a ON a.id = c.artifact_id_a
                   WHERE a.expert_id = ?
                   ORDER BY c.detected_at DESC""",
                (expert_id,),
            )
        else:
            rows = conn.execute(
                "SELECT * FROM artifact_conflicts ORDER BY detected_at DESC"
            )
        return [dict(r) for r in rows]


def delete_artifact_conflicts_for_expert(expert_id: int) -> None:
    """Remove all conflicts for an expert so the consistency checker can re-run cleanly."""
    with _conn() as conn:
        conn.execute(
            """DELETE FROM artifact_conflicts
               WHERE artifact_id_a IN (
                   SELECT id FROM knowledge_artifacts WHERE expert_id=?
               )""",
            (expert_id,),
        )


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict[str, int]:
    with _conn() as conn:
        return {
            "experts": conn.execute("SELECT COUNT(*) FROM experts").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM interview_sessions").fetchone()[0],
            "artifacts": conn.execute("SELECT COUNT(*) FROM knowledge_artifacts").fetchone()[0],
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        }

from __future__ import annotations
"""
SQLite persistence layer.

Stands in for PostgreSQL + SQLAlchemy from the full spec (section 32/33).
Same normalized entity set, plain sqlite3 + hand-written SQL so it needs
zero third-party packages. Swapping this module out for a SQLAlchemy
engine pointed at Postgres is the documented upgrade path (see README).
"""
import json
import sqlite3
import threading
import time
import uuid

from app.config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_uid TEXT NOT NULL DEFAULT 'local',
    original_filename TEXT,
    storage_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UPLOADED',
    created_at REAL NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'upload',   -- upload | git
    git_url TEXT,
    git_branch TEXT,
    git_commit TEXT
);

CREATE TABLE IF NOT EXISTS project_analysis (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    languages_json TEXT,
    framework TEXT,
    execution_status TEXT,          -- SUPPORTED / PARTIALLY_SUPPORTED / ANALYZED_BUT_NOT_EXECUTABLE / UNSUPPORTED
    components_json TEXT,
    structure_json TEXT,
    entrypoint_json TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at REAL NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS failure_points (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    component TEXT NOT NULL,
    type TEXT NOT NULL,
    dependencies_json TEXT,
    failure_modes_json TEXT,
    coverage_status TEXT NOT NULL DEFAULT 'NOT_TESTED',
    created_at REAL NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    failure_point_id TEXT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    target TEXT NOT NULL,
    fault_type TEXT NOT NULL,
    parameters_json TEXT,
    risk_level INTEGER NOT NULL,
    expected_behavior TEXT,
    safety_requirements_json TEXT,
    status TEXT NOT NULL DEFAULT 'GENERATED',   -- GENERATED / BLOCKED / READY
    block_reason TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id),
    FOREIGN KEY(failure_point_id) REFERENCES failure_points(id)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    started_at REAL,
    finished_at REAL,
    outcome TEXT,                    -- one of the detection classifications
    sandbox_path TEXT,
    baseline_json TEXT,
    chaos_json TEXT,
    error TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,              -- INJECTED_FAULT / APPLICATION_FAILURE / SECONDARY_FAILURE / RECOVERY / SYSTEM
    message TEXT,
    data_json TEXT,
    FOREIGN KEY(run_id) REFERENCES experiment_runs(id)
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    failure TEXT,
    root_cause TEXT,
    affected_component TEXT,
    impact TEXT,
    evidence_json TEXT,
    recommended_fix TEXT,
    resilience_pattern TEXT,
    confidence REAL,
    method TEXT NOT NULL,            -- rule_based | llm
    created_at REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES experiment_runs(id)
);

CREATE TABLE IF NOT EXISTS safety_events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    project_id TEXT,
    decision TEXT NOT NULL,          -- ALLOWED / BLOCKED
    reason TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tutor_sessions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    explanation_json TEXT NOT NULL,
    question_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES experiment_runs(id)
);

CREATE TABLE IF NOT EXISTS user_answers (
    id TEXT PRIMARY KEY,
    tutor_session_id TEXT NOT NULL,
    answer_text TEXT,
    correct INTEGER,
    feedback TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(tutor_session_id) REFERENCES tutor_sessions(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    details_json TEXT
);
"""


def get_conn():
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return _local.conn


_init_lock = threading.Lock()
_initialized = False


def _ensure_columns(conn):
    """Bring a projects table created by an older version up to date.
    CREATE TABLE IF NOT EXISTS never adds columns to an existing table."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "owner_uid" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN owner_uid TEXT NOT NULL DEFAULT 'local'")
    for col, ddl in (
        ("source_type", "ALTER TABLE projects ADD COLUMN source_type TEXT NOT NULL DEFAULT 'upload'"),
        ("git_url", "ALTER TABLE projects ADD COLUMN git_url TEXT"),
        ("git_branch", "ALTER TABLE projects ADD COLUMN git_branch TEXT"),
        ("git_commit", "ALTER TABLE projects ADD COLUMN git_commit TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)


def init_db():
    global _initialized
    with _init_lock:
        conn = get_conn()
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        conn.commit()
        _initialized = True


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


def insert(table: str, row: dict):
    conn = get_conn()
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    values = list(row.values())
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
    conn.commit()


def update(table: str, id_: str, fields: dict):
    conn = get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [id_]
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", values)
    conn.commit()


def get_one(table: str, id_: str):
    conn = get_conn()
    cur = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_many(table: str, where: str = "", params=()):
    conn = get_conn()
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    columns = _columns(table)
    # experiment_runs predates the common created_at column and uses
    # started_at as its chronological timestamp. Without an explicit
    # ordering, SQLite returns rows in insertion/rowid order, which can
    # make the Runs UI show older executions before newer ones.
    if "created_at" in columns:
        sql += " ORDER BY created_at DESC"
    elif table == "experiment_runs" and "started_at" in columns:
        sql += " ORDER BY started_at DESC"
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def _columns(table: str):
    conn = get_conn()
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


def loads(s):
    if s is None:
        return None
    return json.loads(s)


def audit(action: str, details: dict, actor: str = "system"):
    insert("audit_log", {
        "id": new_id(),
        "ts": now(),
        "actor": actor,
        "action": action,
        "details_json": dumps(details),
    })

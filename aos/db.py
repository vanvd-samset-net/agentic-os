"""CSDL SQLite của control plane (docs/02-du-lieu.md). Chỉ thư viện chuẩn."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("AOS_DATA_DIR") or ROOT / "data")

SCHEMA = [
    # v1
    """
    CREATE TABLE organizations (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, mission TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE agents (
        id TEXT PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '', reports_to TEXT, adapter TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')), updated_at TEXT NOT NULL
    );
    CREATE TABLE goals (
        id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), parent_id INTEGER REFERENCES goals(id),
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
    );
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), goal_id INTEGER REFERENCES goals(id),
        slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), parent_id INTEGER REFERENCES tasks(id),
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', agent_id TEXT REFERENCES agents(id),
        status TEXT NOT NULL DEFAULT 'backlog' CHECK (status IN
            ('backlog', 'assigned', 'running', 'under_review', 'done', 'failed', 'blocked', 'cancelled')),
        priority INTEGER NOT NULL DEFAULT 2, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 2,
        lock_owner TEXT, lock_until TEXT, blocked_reason TEXT, result_summary TEXT,
        created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX tasks_queue ON tasks (agent_id, status, priority, id);
    CREATE TABLE task_deps (
        task_id INTEGER NOT NULL REFERENCES tasks(id), depends_on INTEGER NOT NULL REFERENCES tasks(id),
        PRIMARY KEY (task_id, depends_on), CHECK (task_id <> depends_on)
    );
    CREATE TABLE task_comments (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), author TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'feedback', 'plan', 'agent')), body TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), agent_id TEXT NOT NULL, worker_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running' CHECK (status IN
            ('running', 'succeeded', 'failed', 'blocked', 'timeout', 'lost', 'cancelled')),
        started_at TEXT NOT NULL, ended_at TEXT, exit_code INTEGER, session_id TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0, num_turns INTEGER, log_dir TEXT, error TEXT
    );
    CREATE INDEX runs_task ON runs (task_id);
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
        entity TEXT NOT NULL, entity_id TEXT, data_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log chỉ được thêm'); END;
    CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log chỉ được thêm'); END;
    """,
    # v2 (Phase 3): trạng thái needs_approval; ngân sách; phê duyệt; quyền công cụ cấp theo task.
    # SQLite không sửa được CHECK tại chỗ → dựng lại bảng tasks, giữ nguyên dữ liệu và id.
    """
    CREATE TABLE tasks_v2 (
        id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), parent_id INTEGER REFERENCES tasks(id),
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', agent_id TEXT REFERENCES agents(id),
        status TEXT NOT NULL DEFAULT 'backlog' CHECK (status IN
            ('backlog', 'assigned', 'running', 'needs_approval', 'under_review', 'done', 'failed', 'blocked', 'cancelled')),
        priority INTEGER NOT NULL DEFAULT 2, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 2,
        lock_owner TEXT, lock_until TEXT, blocked_reason TEXT, result_summary TEXT,
        created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    INSERT INTO tasks_v2 SELECT id, project_id, parent_id, title, description, agent_id, status, priority, attempts,
        max_attempts, lock_owner, lock_until, blocked_reason, result_summary, created_by, created_at, updated_at FROM tasks;
    DROP TABLE tasks;
    ALTER TABLE tasks_v2 RENAME TO tasks;
    CREATE INDEX tasks_queue ON tasks (agent_id, status, priority, id);
    CREATE TABLE budgets (
        id INTEGER PRIMARY KEY, scope TEXT NOT NULL CHECK (scope IN ('org', 'project', 'agent', 'task')),
        scope_id TEXT NOT NULL DEFAULT '', period TEXT NOT NULL DEFAULT 'total' CHECK (period IN ('total', 'month')),
        limit_usd REAL, limit_tokens INTEGER, warn_ratio REAL NOT NULL DEFAULT 0.8,
        warned_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (scope, scope_id, period)
    );
    CREATE TABLE approvals (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), run_id INTEGER REFERENCES runs(id),
        kind TEXT NOT NULL CHECK (kind IN ('budget', 'tool')),
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied')),
        request_json TEXT NOT NULL DEFAULT '{}', requested_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT,
        decision_note TEXT
    );
    CREATE INDEX approvals_pending ON approvals (status, task_id);
    CREATE TABLE task_grants (
        task_id INTEGER NOT NULL REFERENCES tasks(id), rule TEXT NOT NULL, approval_id INTEGER REFERENCES approvals(id),
        granted_by TEXT NOT NULL, granted_at TEXT NOT NULL, PRIMARY KEY (task_id, rule)
    );
    """,
]


def now(delta_seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat(timespec="seconds")


def db_path():
    return Path(os.environ.get("AOS_DB") or DATA / "aos.db")


def connect(path=None):
    """Kết nối có khoá ngoại, WAL, chờ khoá tối đa 30 giây. isolation_level=None: tự quản lý giao dịch."""
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 30000")
    migrate(con)
    return con


def migrate(con):
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = con.execute("SELECT version FROM schema_version").fetchone()
    version = row["version"] if row else 0
    if version >= len(SCHEMA):
        return
    # Dựng lại bảng cần tắt khoá ngoại (chỉ đổi được ngoài giao dịch); kiểm lại toàn vẹn trước khi COMMIT.
    con.execute("PRAGMA foreign_keys = OFF")
    try:
        for i, script in enumerate(SCHEMA[version:], start=version + 1):
            con.execute("BEGIN IMMEDIATE")
            try:
                for stmt in split_sql(script):
                    con.execute(stmt)
                bad = con.execute("PRAGMA foreign_key_check").fetchall()
                if bad:
                    raise sqlite3.IntegrityError(f"Nâng cấp CSDL v{i} làm hỏng khoá ngoại: {len(bad)} dòng")
                con.execute("DELETE FROM schema_version")
                con.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
    finally:
        con.execute("PRAGMA foreign_keys = ON")


def split_sql(script):
    """Tách câu lệnh, giữ nguyên thân trigger (BEGIN ... END;)."""
    out, buf = [], []
    for line in script.splitlines():
        if not line.strip():
            continue
        buf.append(line)
        joined = "\n".join(buf).strip()
        if joined.endswith(";") and (not joined.upper().startswith("CREATE TRIGGER") or joined.upper().endswith("END;")):
            out.append(joined)
            buf = []
    if buf:
        out.append("\n".join(buf))
    return out


class Tx:
    """Giao dịch ghi: BEGIN IMMEDIATE giữ khoá ghi ngay từ đầu → checkout nguyên tử giữa nhiều worker."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, exc_type, exc, tb):
        self.con.execute("ROLLBACK" if exc_type else "COMMIT")
        return False

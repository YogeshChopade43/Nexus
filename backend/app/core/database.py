from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    path = Path(os.getenv("DATABASE_PATH", DATABASE_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    # timeout: wait on locks instead of failing when the scheduler and API write concurrently.
    conn = sqlite3.connect(get_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_activity(
    activity_type: str,
    title: str,
    description: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Record an activity entry. Never raises: activity logging must not break callers."""
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO activity_log (type, title, description, metadata, timestamp) VALUES (?, ?, ?, ?, ?)",
                (
                    activity_type,
                    title[:200],
                    description[:1000],
                    json.dumps(metadata or {}, default=str),
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to record activity %s", activity_type)


# Schema changes after the baseline in init_db, applied once each in order. The database's
# PRAGMA user_version records how many have run. Append only: never edit or reorder an entry.
MIGRATIONS: list[str] = [
    # 1: OAuth tokens and client registration for hosted MCP servers (encrypted JSON)
    "ALTER TABLE mcp_servers ADD COLUMN oauth TEXT DEFAULT ''",
    # 2: (removed: users, login sessions and audit log; see 4)
    "SELECT 1",
    # 3: tokens used per AI call, for the dashboard and the daily limit
    """
    CREATE TABLE llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        provider_id INTEGER,
        provider TEXT,
        model TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        estimated INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_llm_usage_ts ON llm_usage(timestamp)
    """,
    # 4: drop the login tables migration 2 used to create
    "DROP TABLE IF EXISTS user_sessions; DROP TABLE IF EXISTS audit_log; DROP TABLE IF EXISTS users",
]


def run_migrations(conn: sqlite3.Connection) -> None:
    applied = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, statement in enumerate(MIGRATIONS[applied:], start=applied + 1):
        logger.info("Applying database migration %d", number)
        conn.executescript(f"BEGIN; {statement}; PRAGMA user_version = {number}; COMMIT;")


def purge_old_records(days: int) -> dict[str, int]:
    """Delete finished workflow runs and activity entries older than ``days`` (0 keeps everything)."""
    if days <= 0:
        return {"runs": 0, "activity": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    conn = get_connection()
    try:
        runs = conn.execute("DELETE FROM workflow_runs WHERE status != 'running' AND started_at < ?", (cutoff,)).rowcount
        activity = conn.execute("DELETE FROM activity_log WHERE timestamp < ?", (cutoff,)).rowcount
        conn.commit()
    finally:
        conn.close()
    if runs or activity:
        logger.info("Cleanup removed %d run(s) and %d activity entries older than %d days", runs, activity, days)
    return {"runs": runs, "activity": activity}


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                steps TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                trigger TEXT DEFAULT 'manual',
                last_run TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                input_data TEXT DEFAULT '{}',
                output TEXT DEFAULT '{}',
                error TEXT,
                events TEXT DEFAULT '[]',
                trace TEXT DEFAULT '[]',
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS workflow_run_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                workflow_id INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                tool_name TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                input_data TEXT DEFAULT '{}',
                output_data TEXT DEFAULT '{}',
                error TEXT,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                timezone TEXT DEFAULT 'UTC',
                enabled INTEGER DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS webhook_endpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                path TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS llm_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_name TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT,
                base_url TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                title TEXT,
                messages TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                settings TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS api_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                settings TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                metadata TEXT DEFAULT '{}',
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                user_id TEXT DEFAULT 'user'
            );
            """
        )
        workflow_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workflows)").fetchall()
        }
        migrations = {
            "nodes": "ALTER TABLE workflows ADD COLUMN nodes TEXT NOT NULL DEFAULT '[]'",
            "edges": "ALTER TABLE workflows ADD COLUMN edges TEXT NOT NULL DEFAULT '[]'",
            "version": "ALTER TABLE workflows ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "is_active": "ALTER TABLE workflows ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "updated_at": "ALTER TABLE workflows ADD COLUMN updated_at TEXT",
            "created_by": "ALTER TABLE workflows ADD COLUMN created_by TEXT",
            "schedule": "ALTER TABLE workflows ADD COLUMN schedule TEXT DEFAULT '{}'",
            "webhook": "ALTER TABLE workflows ADD COLUMN webhook TEXT DEFAULT '{}'",
            "llm_provider_id": "ALTER TABLE workflows ADD COLUMN llm_provider_id INTEGER",
        }
        for column, statement in migrations.items():
            if column not in workflow_columns:
                conn.execute(statement)
        schedule_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(schedules)").fetchall()
        }
        schedule_migrations = {
            "input_data": "ALTER TABLE schedules ADD COLUMN input_data TEXT DEFAULT '{}'",
        }
        for column, statement in schedule_migrations.items():
            if column not in schedule_columns:
                conn.execute(statement)
        webhook_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(webhook_endpoints)").fetchall()
        }
        webhook_migrations = {
            "input_data": "ALTER TABLE webhook_endpoints ADD COLUMN input_data TEXT DEFAULT '{}'",
            "secret": "ALTER TABLE webhook_endpoints ADD COLUMN secret TEXT DEFAULT ''",
        }
        for column, statement in webhook_migrations.items():
            if column in webhook_columns:
                continue
            try:
                conn.execute(statement)
            except Exception:
                pass
        agent_session_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_sessions)").fetchall()
        }
        agent_session_migrations = {
            "title": "ALTER TABLE agent_sessions ADD COLUMN title TEXT",
        }
        for column, statement in agent_session_migrations.items():
            if column not in agent_session_columns:
                try:
                    conn.execute(statement)
                except Exception:
                    pass
        from app.mcp.store import init_table as init_mcp_table

        init_mcp_table(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                snapshot TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS trigger_state (
                workflow_id INTEGER PRIMARY KEY,
                seen TEXT DEFAULT '[]',
                baseline_done INTEGER DEFAULT 0,
                last_checked_at TEXT,
                last_error TEXT,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_runs_workflow ON workflow_runs(workflow_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
            """
        )
        trigger_state_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trigger_state)").fetchall()}
        if "baseline_at" not in trigger_state_columns:
            conn.execute("ALTER TABLE trigger_state ADD COLUMN baseline_at TEXT")
        run_migrations(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def migrate_llm_api_keys() -> None:
    """Encrypt any plaintext LLM API keys already stored in the database.

    Idempotent: values already prefixed with ``fernet-llm:`` are left alone.
    Requires ``NEXUS_SECRET_KEY`` to be set; skips silently if it is missing so
    that the app still starts in degraded mode rather than crashing.
    """
    import os

    if not os.getenv("NEXUS_SECRET_KEY"):
        return
    from app.core.secrets import encrypt_api_key, LLM_KEY_PREFIX

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, api_key FROM llm_providers WHERE api_key IS NOT NULL AND api_key != ''"
        ).fetchall()
        for row in rows:
            api_key = row["api_key"]
            if not api_key or api_key.startswith(LLM_KEY_PREFIX):
                continue
            encrypted = encrypt_api_key(api_key)
            if encrypted and encrypted != api_key:
                conn.execute(
                    "UPDATE llm_providers SET api_key = ?, updated_at = datetime('now') WHERE id = ?",
                    (encrypted, row["id"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

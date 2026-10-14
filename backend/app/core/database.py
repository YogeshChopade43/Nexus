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


def database_url() -> str:
    """PostgreSQL (production) when DATABASE_URL names one; otherwise SQLite at DATABASE_PATH (local, tests)."""
    url = os.getenv("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else ""


def is_postgres() -> bool:
    return bool(database_url())


def get_connection() -> sqlite3.Connection:
    if is_postgres():
        from app.core import pg

        return pg.connect(database_url())  # type: ignore[return-value]  # the sqlite3 API subset the app uses
    # timeout: wait on locks instead of failing when the scheduler and API write concurrently.
    conn = sqlite3.connect(get_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _acting_user_id() -> Optional[int]:
    """Whom an activity belongs to: the signed-in person, or the person a background job acts for (None: no one yet)."""
    from app.auth.context import current_user

    user = current_user.get()
    return int(user["id"]) if user else None


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
                "INSERT INTO activity_log (type, title, description, metadata, timestamp, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    activity_type,
                    title[:200],
                    description[:1000],
                    json.dumps(metadata or {}, default=str),
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    _acting_user_id(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to record activity %s", activity_type)


# Schema changes after the baseline in init_db, applied once each in order. The database's
# PRAGMA user_version records how many have run. Append only: never edit or reorder an entry.
# PostgreSQL installs start from schema_postgres.sql (everything below included) and run only later entries, so
# a new entry must be SQL both accept (ALTER TABLE ... ADD COLUMN, CREATE TABLE/INDEX) and goes into that file too.
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
    # 5: documents the agent can search (full-text index) and facts it remembers
    """
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        chars INTEGER NOT NULL,
        chunks INTEGER NOT NULL,
        session_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE document_chunks USING fts5(doc_id UNINDEXED, name UNINDEXED, position UNINDEXED, content);
    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    # 6: production RAG (docs/superpowers/specs/2026-10-08-production-rag-design.md section 2).
    # The migration-5 document tables are kept as legacy_* until their contents are imported.
    """
    ALTER TABLE documents RENAME TO legacy_documents;
    ALTER TABLE document_chunks RENAME TO legacy_document_chunks;
    CREATE TABLE workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    INSERT INTO workspaces (id, name) VALUES (1, 'Default');
    CREATE TABLE collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('library', 'chat')),
        session_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX idx_collections_library_name ON collections(workspace_id, name) WHERE kind = 'library';
    CREATE UNIQUE INDEX idx_collections_chat ON collections(session_id) WHERE kind = 'chat';
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        mime TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'ready', 'failed')),
        error TEXT,
        progress INTEGER NOT NULL DEFAULT 0,
        pages INTEGER,
        chars INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        embed_model TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (collection_id, content_hash)
    );
    CREATE INDEX idx_documents_collection ON documents(collection_id, status);
    CREATE TABLE document_files (
        document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        data BLOB NOT NULL
    );
    CREATE TABLE chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        workspace_id INTEGER NOT NULL,
        parent_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('parent', 'child')),
        position INTEGER NOT NULL,
        text TEXT NOT NULL,
        heading_path TEXT NOT NULL DEFAULT '',
        page_start INTEGER,
        page_end INTEGER,
        char_start INTEGER NOT NULL DEFAULT 0,
        char_end INTEGER NOT NULL DEFAULT 0,
        tokens INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_chunks_document ON chunks(document_id, kind, position);
    CREATE VIRTUAL TABLE chunk_fts USING fts5(text, heading_path, document_name);
    CREATE TABLE ingestion_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'retry', 'done', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL,
        last_error TEXT,
        progress INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_jobs_due ON ingestion_jobs(status, next_attempt_at);
    CREATE TABLE retrieval_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        session_id TEXT,
        query TEXT NOT NULL,
        rewritten_query TEXT,
        filters_json TEXT NOT NULL DEFAULT '{}',
        candidates_json TEXT NOT NULL DEFAULT '[]',
        selected_json TEXT NOT NULL DEFAULT '[]',
        latency_ms_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE TABLE answer_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        retrieval_log_id INTEGER REFERENCES retrieval_logs(id) ON DELETE SET NULL,
        message_ref TEXT,
        rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
        comment TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE embedding_cache (
        key TEXT PRIMARY KEY,
        vector BLOB NOT NULL
    )
    """,
    # 7: English stemming in the keyword index ("refund" finds "refunds"), rebuilt from existing chunks
    """
    DROP TABLE chunk_fts;
    CREATE VIRTUAL TABLE chunk_fts USING fts5(text, heading_path, document_name, tokenize = 'porter unicode61');
    INSERT INTO chunk_fts (rowid, text, heading_path, document_name)
        SELECT c.id,
               d.name || CASE WHEN c.heading_path != '' THEN ' › ' || c.heading_path ELSE '' END || char(10, 10) || c.text,
               c.heading_path, d.name
        FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.kind = 'child'
    """,
    # 8: answer feedback (thumbs up/down) removed
    "DROP TABLE IF EXISTS answer_feedback",
    # 9: Marketplace: a local copy of the MCP Registry (docs/superpowers/specs/2026-10-09-mcp-marketplace-design.md)
    """
    CREATE TABLE registry_servers (
        name TEXT PRIMARY KEY, title TEXT, description TEXT NOT NULL DEFAULT '', version TEXT,
        icon_url TEXT, repository_url TEXT, website_url TEXT,
        install_json TEXT, kind TEXT, match_key TEXT, updated_at TEXT
    );
    CREATE INDEX registry_servers_match ON registry_servers(match_key);
    CREATE VIRTUAL TABLE registry_fts USING fts5(name, title, description, tokenize = 'porter unicode61');
    CREATE TABLE registry_sync (
        id INTEGER PRIMARY KEY CHECK (id = 1), last_synced_at TEXT, status TEXT, error TEXT, count INTEGER
    )
    """,
    # 10: Marketplace "Official" badge (filled by registry.backfill_official for rows stored before it)
    "ALTER TABLE registry_servers ADD COLUMN official INTEGER",
    # 11: Marketplace front page: test/staging/empty listings flagged; title index for duplicate checks
    "ALTER TABLE registry_servers ADD COLUMN junk INTEGER; CREATE INDEX registry_servers_title ON registry_servers(title)",
    # 12: registry_servers gets an explicit INTEGER PRIMARY KEY (same values as the old implicit rowids, which
    # registry_fts is joined on): implicit rowids may be renumbered by VACUUM, desyncing the search index.
    """
    CREATE TABLE registry_servers_new (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, title TEXT, description TEXT NOT NULL DEFAULT '',
        version TEXT, icon_url TEXT, repository_url TEXT, website_url TEXT, install_json TEXT, kind TEXT,
        match_key TEXT, updated_at TEXT, official INTEGER, junk INTEGER
    );
    INSERT INTO registry_servers_new (id, name, title, description, version, icon_url, repository_url, website_url,
                                      install_json, kind, match_key, updated_at, official, junk)
        SELECT rowid, name, title, description, version, icon_url, repository_url, website_url, install_json, kind,
               match_key, updated_at, official, junk FROM registry_servers;
    DROP TABLE registry_servers;
    ALTER TABLE registry_servers_new RENAME TO registry_servers;
    CREATE INDEX registry_servers_match ON registry_servers(match_key);
    CREATE INDEX registry_servers_title ON registry_servers(title)
    """,
    # 13: hosted MCP servers only: listings Nexus would have to run on this computer are dropped
    """
    DELETE FROM registry_fts WHERE rowid IN (SELECT id FROM registry_servers WHERE kind IS NOT 'hosted');
    DELETE FROM registry_servers WHERE kind IS NOT 'hosted'
    """,
    # 14: built-in integrations (email, calendar feeds, RSS...): settings encrypted like MCP secrets
    """
    CREATE TABLE integrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        config TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    # 15: memories Nexus learned by itself (auto) beside the ones the user asked for (manual)
    """
    ALTER TABLE memories ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'
    """,
    # 16: workflows grouped in folders ('' = no folder)
    """
    ALTER TABLE workflows ADD COLUMN folder TEXT NOT NULL DEFAULT ''
    """,
    # 17: run-once workflows: one run, on a date ('at') or if you go quiet ('quiet')
    """
    CREATE TABLE run_once (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        at TEXT,
        days INTEGER,
        enabled INTEGER NOT NULL DEFAULT 1,
        armed_at TEXT,
        warned_at TEXT,
        reminded_at TEXT,
        ran_at TEXT,
        missed_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    # 18: accounts and their sign-in sessions (only a token's SHA-256 is kept)
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        password_hash TEXT,
        email_verified INTEGER NOT NULL DEFAULT 0,
        google_sub TEXT UNIQUE,
        is_admin INTEGER NOT NULL DEFAULT 0,
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT ''
    )
    """,
    # 19: an owner for each "root" row (children are reached through them); NULL = from before accounts,
    # claimed by the first account
    """
    ALTER TABLE workflows ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_workflows_user ON workflows(user_id);
    ALTER TABLE agent_sessions ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_agent_sessions_user ON agent_sessions(user_id);
    ALTER TABLE llm_providers ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_llm_providers_user ON llm_providers(user_id);
    ALTER TABLE mcp_servers ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_mcp_servers_user ON mcp_servers(user_id);
    ALTER TABLE integrations ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_integrations_user ON integrations(user_id);
    ALTER TABLE memories ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
    ALTER TABLE activity_log RENAME COLUMN user_id TO legacy_user;
    ALTER TABLE activity_log ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_activity_log_user ON activity_log(user_id);
    ALTER TABLE llm_usage ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_llm_usage_user ON llm_usage(user_id);
    ALTER TABLE user_settings ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);
    ALTER TABLE workspaces ADD COLUMN user_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_workspaces_user ON workspaces(user_id)
    """,
    # 20: one-time links sent by email (verify an address, reset a password); only a token's SHA-256 is kept
    """
    CREATE TABLE email_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        purpose TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    )
    """,
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


def _init_postgres(conn: Any) -> None:
    """A fresh database gets the whole schema at once; later migrations (written to run on both) apply in order."""
    conn.execute("SELECT pg_advisory_xact_lock(4711)")  # several app processes starting together: one sets up
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.executescript((Path(__file__).parent / "schema_postgres.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (len(MIGRATIONS),))
    else:
        for number, statement in enumerate(MIGRATIONS[row[0]:], start=row[0] + 1):
            logger.info("Applying database migration %d", number)
            conn.executescript(statement)
            conn.execute("UPDATE schema_version SET version = ?", (number,))
    conn.commit()


def init_db() -> None:
    conn = get_connection()
    if is_postgres():
        try:
            _init_postgres(conn)
        finally:
            conn.close()
        return
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

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Tuple

from app.core.config import DATABASE_PATH
from app.core.secrets import decrypt_config, encrypt_config


def get_db_path() -> Path:
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_app_states(conn: sqlite3.Connection) -> dict[str, dict[str, bool]]:
    rows = conn.execute(
        """
        SELECT a.app_id, a.enabled,
               COALESCE(
                   (SELECT c.connected FROM connections c
                    WHERE c.app_id = a.app_id
                    ORDER BY c.id DESC LIMIT 1),
                   0
               ) AS connected
        FROM apps a
        """
    ).fetchall()
    states = {}
    for row in rows:
        enabled = bool(row["enabled"])
        connected = bool(row["connected"])
        states[row["app_id"]] = {
            "enabled": enabled,
            "connected": connected,
            "available": enabled and connected,
        }
    return states


def get_effective_app_connections(conn: sqlite3.Connection) -> dict[str, bool]:
    return {
        app_id: state["available"]
        for app_id, state in get_app_states(conn).items()
    }


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS apps (
                app_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                icon TEXT,
                enabled INTEGER DEFAULT 1,
                capabilities TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id TEXT NOT NULL,
                connected INTEGER DEFAULT 0,
                config TEXT DEFAULT '{}',
                connected_at TEXT,
                disconnected_at TEXT,
                FOREIGN KEY (app_id) REFERENCES apps(app_id) ON DELETE CASCADE
            );
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
            CREATE TABLE IF NOT EXISTS tool_registry (
                tool_name TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                description TEXT,
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (app_id) REFERENCES apps(app_id) ON DELETE CASCADE
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
        }
        for column, statement in migrations.items():
            if column not in workflow_columns:
                conn.execute(statement)
        conn.commit()
    finally:
        conn.close()

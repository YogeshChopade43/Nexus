"""Persistence for configured MCP servers. Secrets (env, headers) are encrypted at rest."""
from __future__ import annotations

import os

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.database import get_connection
from app.core.secrets import decrypt_config, encrypt_config

MASK = "***"


@dataclass
class ServerConfig:
    id: int
    slug: str
    name: str
    transport: str  # "stdio" | "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    tool_policies: dict[str, str] = field(default_factory=dict)  # remote tool name -> allow | ask | block
    signed_in: bool = False  # holds OAuth tokens from a hosted-server sign-in
    registry_name: str = ""  # the MCP Registry listing it was installed from (Marketplace)

    def public(self) -> dict[str, Any]:
        """API view: secret values are never returned, only their names."""
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "env": {key: MASK for key in self.env},
            "url": self.url,
            "headers": {key: MASK for key in self.headers},
            "enabled": self.enabled,
            "created_at": self.created_at,
            "tool_policies": self.tool_policies,
            "signed_in": self.signed_in,
            "registry_name": self.registry_name,
        }


def local_servers_allowed() -> bool:
    """Nexus connects to hosted MCP servers only. Launching local ones (code execution on this machine) stays
    behind this switch, which only the test suite turns on (its fixture servers are local programs)."""
    return os.getenv("NEXUS_ALLOW_LOCAL_SERVERS", "").lower() == "true"


def init_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            transport TEXT NOT NULL,
            command TEXT DEFAULT '',
            args TEXT DEFAULT '[]',
            env TEXT DEFAULT '{}',
            url TEXT DEFAULT '',
            headers TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(mcp_servers)").fetchall()}
    if "tool_policies" not in columns:
        conn.execute("ALTER TABLE mcp_servers ADD COLUMN tool_policies TEXT DEFAULT '{}'")
    if "registry_name" not in columns:
        conn.execute("ALTER TABLE mcp_servers ADD COLUMN registry_name TEXT DEFAULT ''")


def _from_row(row: Any) -> ServerConfig:
    return ServerConfig(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        transport=row["transport"],
        command=row["command"] or "",
        args=json.loads(row["args"] or "[]"),
        env=decrypt_config(row["env"]),
        url=row["url"] or "",
        headers=decrypt_config(row["headers"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"] or "",
        tool_policies=json.loads(row["tool_policies"] or "{}") if "tool_policies" in row.keys() else {},
        signed_in=bool(decrypt_config(row["oauth"]).get("tokens")) if "oauth" in row.keys() and row["oauth"] else False,
        registry_name=(row["registry_name"] or "") if "registry_name" in row.keys() else "",
    )


def slugify(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:24] or "server"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    return slug


def list_servers() -> list[ServerConfig]:
    conn = get_connection()
    try:
        return [_from_row(r) for r in conn.execute("SELECT * FROM mcp_servers ORDER BY name").fetchall()]
    finally:
        conn.close()


def get_server(server_id: int) -> Optional[ServerConfig]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        return _from_row(row) if row else None
    finally:
        conn.close()


def _merge_secrets(new: dict[str, str], old: dict[str, str]) -> dict[str, str]:
    """A value of MASK means "keep what is stored" (the UI only ever sees MASK)."""
    return {key: old.get(key, "") if value == MASK else value for key, value in new.items()}


def create_server(data: dict[str, Any]) -> ServerConfig:
    conn = get_connection()
    try:
        from app.integrations.store import taken_slugs  # MCP servers and integrations share tool-name prefixes

        taken = taken_slugs(conn)
        cursor = conn.execute(
            """
            INSERT INTO mcp_servers (slug, name, transport, command, args, env, url, headers, enabled, tool_policies,
                                     registry_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slugify(data["name"], taken), data["name"], data["transport"], data.get("command", ""),
                json.dumps(data.get("args", [])), encrypt_config(data.get("env", {})), data.get("url", ""),
                encrypt_config(data.get("headers", {})), int(data.get("enabled", True)),
                json.dumps(data.get("tool_policies") or {}), data.get("registry_name", ""),
            ),
        )
        conn.commit()
        server_id = cursor.lastrowid
    finally:
        conn.close()
    return get_server(server_id)


def update_server(server_id: int, data: dict[str, Any]) -> Optional[ServerConfig]:
    current = get_server(server_id)
    if current is None:
        return None
    env = _merge_secrets(data["env"], current.env) if "env" in data else current.env
    headers = _merge_secrets(data["headers"], current.headers) if "headers" in data else current.headers
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE mcp_servers SET name = ?, transport = ?, command = ?, args = ?, env = ?, url = ?,
                headers = ?, enabled = ?, tool_policies = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                data.get("name", current.name), data.get("transport", current.transport),
                data.get("command", current.command), json.dumps(data.get("args", current.args)),
                encrypt_config(env), data.get("url", current.url), encrypt_config(headers),
                int(data.get("enabled", current.enabled)), json.dumps(data.get("tool_policies", current.tool_policies)),
                server_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_server(server_id)


def delete_server(server_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_oauth(server_id: int) -> dict[str, Any]:
    """``{"tokens": ..., "client_info": ...}`` saved by the OAuth sign-in, or ``{}``."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT oauth FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        return decrypt_config(row["oauth"]) if row and row["oauth"] else {}
    finally:
        conn.close()


def set_oauth(server_id: int, data: dict[str, Any]) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE mcp_servers SET oauth = ? WHERE id = ?", (encrypt_config(data) if data else "", server_id))
        conn.commit()
    finally:
        conn.close()

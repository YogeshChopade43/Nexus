"""Connected integrations, with their settings encrypted at rest (the same key as MCP secrets)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.database import get_connection
from app.core.secrets import decrypt_config, encrypt_config
from app.mcp.store import slugify


def taken_slugs(conn) -> set[str]:
    """Slugs in use by integrations and MCP servers: tool names (slug__tool) must never clash."""
    return ({r[0] for r in conn.execute("SELECT slug FROM integrations")}
            | {r[0] for r in conn.execute("SELECT slug FROM mcp_servers")})


def _row(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "kind": row["kind"], "name": row["name"], "slug": row["slug"],
            "config": decrypt_config(row["config"]), "enabled": bool(row["enabled"]), "created_at": row["created_at"]}


def list_integrations() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [_row(r) for r in conn.execute("SELECT * FROM integrations ORDER BY id")]
    finally:
        conn.close()


def get_integration(integration_id: int) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
        return _row(row) if row else None
    finally:
        conn.close()


def create_integration(kind: str, name: str, config: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO integrations (kind, name, slug, config, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (kind, name, slugify(name, taken_slugs(conn)), encrypt_config(config),
             datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")))
        conn.commit()
        integration_id = cursor.lastrowid
    finally:
        conn.close()
    return get_integration(integration_id)


def update_integration(integration_id: int, **changes: Any) -> Optional[dict[str, Any]]:
    columns = {"name": changes.get("name"), "enabled": None if changes.get("enabled") is None else int(changes["enabled"]),
               "config": None if changes.get("config") is None else encrypt_config(changes["config"])}
    columns = {k: v for k, v in columns.items() if v is not None}
    if columns:
        conn = get_connection()
        try:
            conn.execute(f"UPDATE integrations SET {', '.join(f'{k} = ?' for k in columns)} WHERE id = ?",
                         (*columns.values(), integration_id))
            conn.commit()
        finally:
            conn.close()
    return get_integration(integration_id)


def delete_integration(integration_id: int) -> bool:
    conn = get_connection()
    try:
        deleted = conn.execute("DELETE FROM integrations WHERE id = ?", (integration_id,)).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()

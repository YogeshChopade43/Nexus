"""Who owns what. Every query on someone's data acts for one person: the signed-in user of the request, or the
user a background job (a scheduled run, a bot message) runs as. With neither, ``owner_id()`` raises: a query
never quietly returns everyone's rows.

Only "root" rows carry ``user_id``; their children (a workflow's runs, a library's documents…) are reached
through them.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from app.auth.context import current_user
from app.core.database import get_connection

OWNED_TABLES = ("workflows", "agent_sessions", "llm_providers", "mcp_servers", "integrations", "memories",
                "activity_log", "llm_usage", "user_settings", "workspaces")


def owner_id() -> int:
    user = current_user.get()
    if user is None:
        raise RuntimeError("There's no signed-in user to act for (use as_user() in background jobs)")
    return int(user["id"])


@contextmanager
def as_user(user_id: int) -> Iterator[None]:
    """Run a background job (a scheduled workflow, a bot message) as the person it belongs to."""
    from app.auth.store import get_user

    token = current_user.set(get_user(user_id) or {"id": user_id})
    try:
        yield
    finally:
        current_user.reset(token)


def app_owners() -> dict[str, Optional[int]]:
    """Each connected app (MCP server or integration, by its tool-name prefix) and who connected it."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT slug, user_id FROM mcp_servers UNION ALL SELECT slug, user_id FROM integrations").fetchall()
    finally:
        conn.close()
    return {row["slug"]: row["user_id"] for row in rows}


def owns_app(app_id: str) -> bool:
    """May the person acting now use this app's tools? Their own apps, and Nexus's built-in ones (no owner)."""
    user = current_user.get()
    if user is None:
        return True  # instance-level code (the managers' own bookkeeping); every user's run acts as its owner
    owners = app_owners()
    return app_id not in owners or owners[app_id] == int(user["id"])


def claim_unowned(user_id: int) -> None:
    """Rows from before accounts existed belong to the install's first account."""
    conn = get_connection()
    try:
        for table in OWNED_TABLES:
            conn.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))
        conn.commit()
    finally:
        conn.close()

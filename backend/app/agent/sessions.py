"""Conversation-session persistence for the agent.

Sessions are stored in the ``agent_sessions`` table. The manager is the only
place that reads/writes session state, so the agent route stays thin and the
streaming + tool-calling logic in ``BaseAgent`` can be reused unchanged.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from app.auth.owner import owner_id
from app.core.database import get_connection, is_postgres

logger = logging.getLogger(__name__)


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if parsed is not None else default


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_session(
    title: str = "",
    metadata: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> str:
    session_id = session_id or str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_sessions (session_id, title, messages, metadata, created_at, updated_at, user_id)
            VALUES (?, ?, '[]', ?, ?, ?, ?)
            """,
            (session_id, title or "", json.dumps(metadata or {}), _now(), _now(), owner_id()),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def get_session(session_id: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ? AND user_id = ?", (session_id, owner_id())
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "title": row["title"] if "title" in row.keys() else "",
            "messages": _load_json(row["messages"], []),
            "metadata": _load_json(row["metadata"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def _pinned() -> str:
    """SQL: whether a conversation is pinned (its metadata JSON's "pinned")."""
    if is_postgres():
        return "COALESCE((metadata::jsonb->>'pinned')::boolean, false)"
    return "COALESCE(json_extract(metadata, '$.pinned'), 0)"


def list_sessions(limit: int = 50, query: str = "") -> list[dict[str, Any]]:
    """Session summaries (no message bodies) for the conversation list; ``query`` matches title or messages."""
    conn = get_connection()
    try:
        if query:
            # Escape LIKE wildcards; search decoded message text (the column is JSON with \u escapes).
            pattern = "%" + query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            messages = ("jsonb_array_elements(agent_sessions.messages::jsonb) m WHERE m->>'content'" if is_postgres() else
                        "json_each(agent_sessions.messages) WHERE json_extract(value, '$.content')")
            rows = conn.execute(
                "SELECT * FROM agent_sessions WHERE user_id = :owner AND (title LIKE :p ESCAPE '!' OR EXISTS ("
                f"  SELECT 1 FROM {messages} LIKE :p ESCAPE '!'"
                f")) ORDER BY {_pinned()} DESC, updated_at DESC LIMIT :limit",
                {"p": pattern, "limit": limit, "owner": owner_id()},
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM agent_sessions WHERE user_id = ? ORDER BY {_pinned()} DESC, updated_at DESC LIMIT ?", (owner_id(), limit)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "title": row["title"] or "",
                "messages": [],
                "metadata": _load_json(row["metadata"], {}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def update_session(session_id: str, title: Optional[str] = None, pinned: Optional[bool] = None) -> bool:
    """Rename or pin a conversation. Leaves ``updated_at`` alone: tidying a chat doesn't make it recent."""
    session = get_session(session_id)
    if session is None:
        return False
    metadata = session["metadata"]
    if pinned is not None:
        metadata["pinned"] = pinned
    conn = get_connection()
    try:
        conn.execute("UPDATE agent_sessions SET title = ?, metadata = ? WHERE session_id = ? AND user_id = ?",
                     (title if title is not None else session["title"], json.dumps(metadata, default=str), session_id, owner_id()))
        conn.commit()
    finally:
        conn.close()
    return True


def delete_session(session_id: str) -> bool:
    """Delete a conversation and the documents attached to it."""
    from app.rag import store

    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_sessions WHERE session_id = ? AND user_id = ?", (session_id, owner_id()))
        conn.commit()
        deleted = cursor.rowcount > 0
        chat = conn.execute("SELECT id FROM collections WHERE kind = 'chat' AND session_id = ?", (session_id,)).fetchone() if deleted else None
    finally:
        conn.close()
    if chat:
        store.delete_collection(chat[0])
    return deleted


def append_message(session_id: str, message: dict[str, Any]) -> dict[str, Any]:
    """Append a message to a session, creating it if missing. Returns the session."""
    session = get_session(session_id)
    if session is None:
        create_session(session_id=session_id)
        session = get_session(session_id)
        if session is None:  # that id is someone else's conversation
            raise LookupError("Conversation not found")

    messages = list(session.get("messages", []))
    messages.append(message)
    messages = messages[-100:]  # cap history to bound token usage

    title = session.get("title") or ""
    if not title and message.get("role") == "user":
        title = (message.get("content") or "")[:80]

    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE agent_sessions
            SET messages = ?, title = ?, updated_at = ?
            WHERE session_id = ? AND user_id = ?
            """,
            (json.dumps(messages, default=str), title, _now(), session_id, owner_id()),
        )
        conn.commit()
    finally:
        conn.close()

    session["messages"] = messages
    session["title"] = title
    session["updated_at"] = _now()
    return session


def replace_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agent_sessions SET messages = ?, updated_at = ? WHERE session_id = ? AND user_id = ?",
            (json.dumps(messages, default=str), _now(), session_id, owner_id()),
        )
        conn.commit()
    finally:
        conn.close()


def set_metadata(session_id: str, metadata: dict[str, Any]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agent_sessions SET metadata = ?, updated_at = ? WHERE session_id = ? AND user_id = ?",
            (json.dumps(metadata, default=str), _now(), session_id, owner_id()),
        )
        conn.commit()
    finally:
        conn.close()


def get_history(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    session = get_session(session_id)
    if session is None:
        return []
    messages = list(session.get("messages", []))
    return messages[-limit:]
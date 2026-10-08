"""Which collections a request may read. The one place to add per-user rules once accounts exist."""
from __future__ import annotations

from typing import Optional

from app.core.database import get_connection


def readable_collections(workspace_id: int, session_id: Optional[str],
                         collection_ids: Optional[list[int]] = None) -> list[int]:
    """The workspace's libraries plus this conversation's own collection (never other chats').
    With ``collection_ids``, only those of them that are readable."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM collections WHERE workspace_id = ? AND (kind = 'library' OR (kind = 'chat' AND session_id = ?))",
            (workspace_id, session_id or ""),
        ).fetchall()
    finally:
        conn.close()
    readable = [r[0] for r in rows]
    if collection_ids is not None:
        wanted = set(collection_ids)
        readable = [c for c in readable if c in wanted]
    return readable

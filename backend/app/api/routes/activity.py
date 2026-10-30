from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.owner import owner_id
from app.core.database import get_connection

router = APIRouter(prefix="/api/activity", tags=["activity"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if parsed is not None else default


def _row_to_activity(row: Any) -> dict[str, Any]:
    metadata = row["metadata"] if "metadata" in row.keys() else None
    user_id = row["user_id"] if "user_id" in row.keys() else "user"
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "title": row["title"],
        "description": row["description"] or "",
        "timestamp": row["timestamp"],
        "metadata": _load_json(metadata, {}),
        "userId": user_id,
    }


def _mine() -> tuple[str, tuple[Any, ...]]:
    """Your activity; the admin also sees events that don't belong to anyone yet (system events)."""
    from app.auth.context import require_user

    user = require_user()
    return "(user_id = ? OR (user_id IS NULL AND ? = 1))", (int(user["id"]), int(bool(user.get("is_admin"))))


@router.get("/")
def list_activity(
    types: Optional[str] = Query(None, description="Comma-separated activity types"),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = get_connection()
    try:
        mine, mine_params = _mine()
        conditions: list[str] = [mine]
        params: list[Any] = list(mine_params)

        if types:
            type_list = [t.strip() for t in types.split(",") if t.strip()]
            if type_list:
                placeholders = ", ".join("?" for _ in type_list)
                conditions.append(f"type IN ({placeholders})")
                params.extend(type_list)

        if dateFrom:
            conditions.append("timestamp >= ?")
            params.append(dateFrom)

        if dateTo:
            conditions.append("timestamp <= ?")
            params.append(dateTo)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM activity_log{where_clause}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM activity_log{where_clause} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        activities = [_row_to_activity(row) for row in rows]
        has_more = (offset + len(activities)) < total

        return {
            "activities": activities,
            "total": total,
            "hasMore": has_more,
        }
    finally:
        conn.close()


@router.post("/")
def create_activity(activity: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    try:
        activity_type = activity.get("type", "settings_changed")
        title = activity.get("title", "")
        description = activity.get("description", "")
        metadata = activity.get("metadata", {})
        user_id = owner_id()  # always yours, whatever the request says
        timestamp = activity.get("timestamp") or _utc_now()

        cursor = conn.execute(
            """
            INSERT INTO activity_log (type, title, description, metadata, timestamp, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                activity_type,
                title,
                description,
                json.dumps(metadata),
                timestamp,
                user_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM activity_log WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_activity(row)
    finally:
        conn.close()


@router.post("/bulk")
def create_activities(activities: list[dict[str, Any]]) -> dict[str, Any]:
    conn = get_connection()
    try:
        created = 0
        for activity in activities:
            activity_type = activity.get("type", "settings_changed")
            title = activity.get("title", "")
            description = activity.get("description", "")
            metadata = activity.get("metadata", {})
            user_id = owner_id()
            timestamp = activity.get("timestamp") or _utc_now()
            conn.execute(
                """
                INSERT INTO activity_log (type, title, description, metadata, timestamp, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (activity_type, title, description, json.dumps(metadata), timestamp, user_id),
            )
            created += 1
        conn.commit()
        return {"created": created}
    finally:
        conn.close()


@router.get("/recent")
def get_recent(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM activity_log WHERE {_mine()[0]} ORDER BY timestamp DESC, id DESC LIMIT ?",
            (*_mine()[1], limit),
        ).fetchall()
        return {
            "activities": [_row_to_activity(row) for row in rows],
            "total": len(rows),
            "hasMore": False,
        }
    finally:
        conn.close()


@router.delete("/{activity_id}")
def delete_activity(activity_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM activity_log WHERE id = ? AND user_id = ?", (activity_id, owner_id()))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Activity not found")
        conn.commit()
        return {"id": activity_id, "deleted": True}
    finally:
        conn.close()


@router.delete("/")
def clear_activities() -> dict[str, Any]:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM activity_log WHERE user_id = ?", (owner_id(),))
        conn.commit()
        return {"deleted": cursor.rowcount}
    finally:
        conn.close()

NOTIFY_TYPES = ("workflow_failed", "server_error", "workflow_resumed", "document_failed", "reminder", "run_once_ran")


@router.get("/notifications")
def get_notifications(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """Things that need attention (failed runs, disconnected servers), reminders, and how many are unread."""
    from app.api.routes.settings import load_user_settings

    settings = load_user_settings()
    types = [t for t in NOTIFY_TYPES if t != "workflow_failed" or settings["notifications"].get("workflowFailure", True)]
    marks = ",".join("?" * len(types))
    read_at = settings.get("notificationsReadAt") or ""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM activity_log WHERE type IN ({marks}) AND {_mine()[0]} ORDER BY id DESC LIMIT ?",
            (*types, *_mine()[1], limit)
        ).fetchall()
        unread = conn.execute(
            f"SELECT COUNT(*) FROM activity_log WHERE type IN ({marks}) AND timestamp > ? AND {_mine()[0]}",
            (*types, read_at, *_mine()[1])
        ).fetchone()[0]
    finally:
        conn.close()
    items = [{**_row_to_activity(row), "unread": row["timestamp"] > read_at} for row in rows]
    return {"unread": unread, "items": items}


@router.post("/notifications/read")
def mark_notifications_read() -> dict[str, Any]:
    from app.api.routes.settings import update_user_settings

    update_user_settings({"notificationsReadAt": _utc_now()})
    return {"unread": 0}


def _approved_action(activity_id: int) -> tuple[dict[str, Any], str]:
    """The entry and its stored metadata text (compared when claiming it for an undo)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM activity_log WHERE id = ? AND user_id = ? AND type = 'action_approved'",
                           (activity_id, owner_id())).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Approved action not found")
    entry = _row_to_activity(row)
    if entry["metadata"].get("undone_at"):
        raise HTTPException(status_code=409, detail="This action was already undone")
    if entry["metadata"].get("undoing"):
        raise HTTPException(status_code=409, detail="This action is being undone")
    return entry, row["metadata"]


def _set_metadata(activity_id: int, metadata: dict[str, Any], expected: Optional[str] = None) -> bool:
    """Write the entry's metadata; with ``expected``, only if nobody changed it since (an atomic claim)."""
    conn = get_connection()
    try:
        if expected is None:
            cursor = conn.execute("UPDATE activity_log SET metadata = ? WHERE id = ?", (json.dumps(metadata, default=str), activity_id))
        else:
            cursor = conn.execute("UPDATE activity_log SET metadata = ? WHERE id = ? AND metadata = ?",
                                  (json.dumps(metadata, default=str), activity_id, expected))
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


class UndoCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/{activity_id}/undo/plan")
async def plan_undo(activity_id: int) -> dict[str, Any]:
    """The call that would reverse an approved action, for the user to confirm."""
    from app import undo

    entry, _ = _approved_action(activity_id)
    try:
        return await undo.plan_undo(entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{activity_id}/undo/run")
async def run_undo(activity_id: int, body: UndoCall) -> dict[str, Any]:
    """Run the reverse call the user confirmed. Each action can be undone once."""
    from app import undo
    from app.core.database import log_activity

    entry, stored = _approved_action(activity_id)
    # Claim it first, so two clicks (or two tabs) can't both run the reverse call.
    if not _set_metadata(activity_id, {**entry["metadata"], "undoing": _utc_now()}, expected=stored):
        raise HTTPException(status_code=409, detail="This action is being undone")
    try:
        result = await undo.run_undo(entry, body.tool, body.arguments)
    except Exception as exc:  # wrong app, app not connected, or the app refused: the action stays undoable
        _set_metadata(activity_id, entry["metadata"])
        detail = str(exc) if isinstance(exc, (ValueError, PermissionError)) else f"The undo failed: {exc}"
        raise HTTPException(status_code=400, detail=detail)
    _set_metadata(activity_id, {**entry["metadata"], "undone_at": _utc_now(), "undo": body.model_dump()})
    log_activity("action_undone", f"Undid: {entry['title']}", metadata={"of": activity_id, **body.model_dump()})
    return {"undone": True, "result": result}

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

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
        conditions: list[str] = []
        params: list[Any] = []

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
        user_id = activity.get("userId", activity.get("user_id", "user"))
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
            user_id = activity.get("userId", activity.get("user_id", "user"))
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
            "SELECT * FROM activity_log ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
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
        cursor = conn.execute("DELETE FROM activity_log WHERE id = ?", (activity_id,))
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
        cursor = conn.execute("DELETE FROM activity_log")
        conn.commit()
        return {"deleted": cursor.rowcount}
    finally:
        conn.close()
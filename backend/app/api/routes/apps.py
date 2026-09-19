from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.core.database import get_app_states, get_connection
from app.models.app import AppResponse
from app.models.connection import ConnectionRequest


router = APIRouter(prefix="/api/apps", tags=["apps"])


async def _validate_credentials(app_id: str, config: dict[str, Any]) -> None:
    if os.getenv("NEXUS_SKIP_VALIDATION", "").lower() == "true":
        return
    from app.connectors import get_connector
    try:
        connector = get_connector(app_id, config)
        await connector.validate()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/", response_model=list[AppResponse])
def list_apps() -> list[AppResponse]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT a.app_id, a.name, a.description, a.category, a.icon, a.enabled, a.capabilities
            FROM apps a
            ORDER BY a.app_id
            """
        ).fetchall()
        states = get_app_states(conn)
        result = []
        for row in rows:
            capabilities = []
            try:
                capabilities = json.loads(row["capabilities"]) if row["capabilities"] else []
            except (json.JSONDecodeError, TypeError):
                capabilities = []
            state = states.get(row["app_id"], {"connected": False})
            result.append(
                AppResponse(
                    app_id=row["app_id"],
                    name=row["name"],
                    description=row["description"],
                    category=row["category"],
                    icon=row["icon"],
                    enabled=bool(row["enabled"]),
                    connected=bool(state["connected"]),
                    capabilities=capabilities,
                )
            )
        return result
    finally:
        conn.close()


@router.get("/{app_id}", response_model=AppResponse)
def get_app(app_id: str) -> AppResponse:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="App not found")
        capabilities = []
        try:
            capabilities = json.loads(row["capabilities"]) if row["capabilities"] else []
        except (json.JSONDecodeError, TypeError):
            capabilities = []
        state = get_app_states(conn).get(app_id, {"connected": False})
        return AppResponse(
            app_id=row["app_id"],
            name=row["name"],
            description=row["description"],
            category=row["category"],
            icon=row["icon"],
            enabled=bool(row["enabled"]),
            connected=bool(state["connected"]),
            capabilities=capabilities,
        )
    finally:
        conn.close()


@router.post("/{app_id}/connection")
async def connect_app(app_id: str, req: ConnectionRequest) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT enabled FROM apps WHERE app_id = ?", (app_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="App not found")

        states = get_app_states(conn)
        current_connected = bool(states.get(app_id, {}).get("connected", False))
        if req.connected is not None:
            connected = bool(req.connected)
        elif req.enabled is not None:
            connected = bool(req.enabled)
        else:
            connected = current_connected

        if connected:
            await _validate_credentials(app_id, req.config or {})

        conn.execute(
            """
            INSERT INTO connections (app_id, connected, config, connected_at, disconnected_at)
            VALUES (?, ?, ?, CASE WHEN ? = 1 THEN datetime('now') ELSE NULL END,
                    CASE WHEN ? = 1 THEN NULL ELSE datetime('now') END)
            """,
            (
                app_id,
                int(connected),
                json.dumps(req.config),
                int(connected),
                int(connected),
            ),
        )
        conn.commit()

        state = get_app_states(conn).get(app_id, {"connected": False})
        return {
            "app_id": app_id,
            "enabled": bool(row["enabled"]),
            "connected": bool(state["connected"]),
            "message": f"{app_id} connected" if state["connected"] else f"{app_id} disconnected",
        }
    finally:
        conn.close()

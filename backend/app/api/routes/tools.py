from __future__ import annotations

from fastapi import APIRouter
from typing import Any
from app.core.database import get_connection
from app.tools import build_tool_registry
from app.tools.base import Tool

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/")
def list_tools() -> dict[str, Any]:
    registry = build_tool_registry()
    tools = []
    for t in registry.get_available_tools():
        tools.append(t.to_dict())
    return {"tools": tools}


@router.get("/available")
def get_available_tools() -> dict[str, Any]:
    registry = build_tool_registry()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT app_id, connected FROM connections WHERE connected = 1").fetchall()
        connected_apps = {r["app_id"] for r in rows}
        tools = [
            t.tool_name
            for t in registry.get_available_tools()
            if t.app_id in connected_apps
        ]
    finally:
        conn.close()
    return {"tools": tools}


@router.get("/app/{app_id}")
def get_tools_for_app(app_id: str) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT connected FROM connections WHERE app_id = ?", (app_id,)).fetchone()
        connected = bool(row["connected"]) if row else False
        registry = build_tool_registry()
        tools = [t.tool_name for t in registry.get_tools_for_app(app_id, app_connected=connected)]
    finally:
        conn.close()
    return {"app_id": app_id, "connected": connected, "tools": tools}


@router.post("/register")
def register_tool(tool_name: str, app_id: str, description: str = "") -> dict[str, str]:
    registry = build_tool_registry()
    tool = Tool(tool_name=tool_name, app_id=app_id, description=description)
    registry.register(tool)
    return {"status": "registered", "tool_name": tool_name}


@router.delete("/{tool_name}")
def unregister_tool(tool_name: str) -> dict[str, str]:
    registry = build_tool_registry()
    registry.unregister(tool_name)
    return {"status": "unregistered", "tool_name": tool_name}
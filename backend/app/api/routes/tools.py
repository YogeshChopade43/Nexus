from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.mcp import server_states
from app.tools import get_tool_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _states() -> dict[str, dict[str, bool]]:
    return server_states()


@router.get("/")
def list_tools(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    states = _states()
    tools = [
        {**t.to_dict(), "available": states.get(t.app_id, {}).get("available", False)}
        for t in get_tool_registry().get_available_tools()
    ]
    return {"tools": tools[offset:offset + limit]}


@router.get("/available")
def get_available_tools() -> dict[str, Any]:
    states = _states()
    tools = [
        t.tool_name
        for t in get_tool_registry().get_available_tools()
        if states.get(t.app_id, {}).get("available", False)
    ]
    return {"tools": tools}


@router.get("/app/{app_id}")
def get_tools_for_app(app_id: str) -> dict[str, Any]:
    connected = _states().get(app_id, {}).get("available", False)
    tools = [t.tool_name for t in get_tool_registry().get_tools_for_app(app_id, app_connected=connected)]
    return {"app_id": app_id, "connected": connected, "tools": tools}

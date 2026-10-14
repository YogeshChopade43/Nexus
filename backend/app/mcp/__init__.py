from __future__ import annotations

from app.knowledge import APP_ID as BUILTIN_APP, register_builtin_tools
from app.mcp.manager import MCPManager
from app.tools import get_tool_registry

# Process-wide manager; started and stopped by the FastAPI lifespan.
mcp_manager = MCPManager(get_tool_registry())
# Nexus's own tools (document search, memory) sit beside the MCP tools and are always available.
register_builtin_tools(get_tool_registry())


def server_states() -> dict[str, dict[str, bool]]:
    from app.integrations import integration_manager  # built-in integrations sit beside MCP servers

    from app.auth.owner import owns_app

    states = {**mcp_manager.server_states(), **integration_manager.states(),
              BUILTIN_APP: {"enabled": True, "connected": True, "available": True}}
    return {app_id: state for app_id, state in states.items() if owns_app(app_id)}  # yours and the built-in ones


def server_availability() -> dict[str, bool]:
    return {app_id: state["available"] for app_id, state in server_states().items()}

from __future__ import annotations

from app.mcp.manager import MCPManager
from app.tools import get_tool_registry

# Process-wide manager; started and stopped by the FastAPI lifespan.
mcp_manager = MCPManager(get_tool_registry())


def server_states() -> dict[str, dict[str, bool]]:
    return mcp_manager.server_states()


def server_availability() -> dict[str, bool]:
    return mcp_manager.availability()

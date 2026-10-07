from __future__ import annotations

from typing import Optional

from app.tools.base import Tool
from app.tools.registry import ToolRegistry

# Shared registry. Tools come from connected MCP servers (see app.mcp.manager).
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry

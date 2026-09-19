from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from app.core.exceptions import AppNotConnectedError, ToolNotFoundError
from app.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.tool_name] = tool

    def unregister(self, tool_name: str) -> None:
        if tool_name in self._tools:
            del self._tools[tool_name]

    def get_tool(self, tool_name: str) -> Tool:
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found")
        return self._tools[tool_name]

    def get_available_tools(self) -> List[Tool]:
        return [t for t in self._tools.values() if t.enabled]

    def get_tools_for_app(self, app_id: str, app_connected: bool = False) -> List[Tool]:
        tools = [t for t in self._tools.values() if t.app_id == app_id and t.enabled]
        if not app_connected:
            return []
        return tools

    async def execute_tool(self, tool_name: str, parameters: dict[str, Any] = {}) -> dict[str, Any]:
        tool = self.get_tool(tool_name)
        if not tool.enabled:
            raise ToolNotFoundError(f"Tool '{tool_name}' is disabled")
        result = await tool.execute(parameters)
        return {
            "tool_name": tool_name,
            "success": True,
            "event": f"Executed {tool_name}",
            "data": result,
        }

    def list_tool_names(self) -> List[str]:
        return sorted(self._tools.keys())
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional



class Tool(ABC):
    def __init__(self, tool_name: str, app_id: str, description: str = "", config: Optional[dict[str, Any]] = None) -> None:
        self.tool_name = tool_name
        self.app_id = app_id
        self.description = description
        self.config = dict(config or {})
        self.enabled = True

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def get_schema(self) -> dict[str, Any]:
        schema = self.parameters_schema
        return {
            "name": self.tool_name,
            "description": self.description,
            "parameters": schema,
        }

    @abstractmethod
    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "app_id": self.app_id,
            "description": self.description,
            "enabled": self.enabled,
            "parameters": self.parameters_schema,
        }

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.core.database import get_connection
from app.core.exceptions import AppNotConnectedError


class Tool(ABC):
    def __init__(self, tool_name: str, app_id: str, description: str = "", config: Optional[dict[str, Any]] = None) -> None:
        self.tool_name = tool_name
        self.app_id = app_id
        self.description = description
        self.config = dict(config or {})
        self.enabled = True

    def _get_connection_config(self, app_id: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT config FROM connections WHERE app_id = ? AND connected = 1 ORDER BY id DESC LIMIT 1",
                (app_id,),
            ).fetchone()
            if row is None:
                raise AppNotConnectedError(f"{app_id} is not connected")
            raw = row["config"]
            if isinstance(raw, str):
                return json.loads(raw) if raw else {}
            return raw or {}
        finally:
            conn.close()

    @abstractmethod
    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "app_id": self.app_id,
            "description": self.description,
            "enabled": self.enabled,
        }

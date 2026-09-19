from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    tool_name: str
    app_id: str
    description: str
    enabled: bool = True


class ToolExecutionRequest(BaseModel):
    tool_name: str
    parameters: dict[str, Any] = {}


class ToolExecutionResult(BaseModel):
    tool_name: str
    success: bool
    event: str
    data: dict[str, Any] = {}
    error: Optional[str] = None
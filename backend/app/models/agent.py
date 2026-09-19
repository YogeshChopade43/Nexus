from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    task: str = ""
    message: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    available_tools: List[str] = Field(default_factory=list)
    llm_provider_id: Optional[int] = None


class AgentRunResponse(BaseModel):
    status: str
    events: List[dict[str, Any]]
    summary: str
    message: str = ""
    response: str = ""

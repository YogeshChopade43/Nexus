from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=1_000_000)


class AgentRunRequest(BaseModel):
    task: str = ""
    message: str = ""
    attachments: List[Attachment] = Field(default_factory=list, max_length=5)
    context: dict[str, Any] = Field(default_factory=dict)
    available_tools: List[str] = Field(default_factory=list)
    llm_provider_id: Optional[int] = None
    session_id: Optional[str] = None
    stream: bool = False


class AgentRunResponse(BaseModel):
    status: str
    events: List[dict[str, Any]]
    summary: str
    message: str = ""
    response: str = ""
    session_id: Optional[str] = None
    pending_action: Optional[dict[str, Any]] = None


class ApprovalRequest(BaseModel):
    approved: bool


class AgentSession(BaseModel):
    id: int
    session_id: str
    title: str = ""
    messages: List[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class AgentSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: Optional[str] = None
    message: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    available_tools: List[str] = Field(default_factory=list)
    llm_provider_id: Optional[int] = None
    stream: bool = False


class AgentSessionCreate(BaseModel):
    title: Optional[str] = None

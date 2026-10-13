from __future__ import annotations

from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=1_000_000)


class FileRef(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{16}$")
    name: str = Field(max_length=200)
    size: int = 0
    url: str = Field(max_length=400)


class ChatSettings(BaseModel):
    """Per-conversation options, saved with the session."""
    servers: Optional[List[str]] = None  # MCP server slugs this chat may use; None = all
    instructions: str = Field(default="", max_length=4000)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    library_id: Optional[int] = None  # answer from this library: retrieve before every message


class AgentRunRequest(BaseModel):
    task: str = ""
    message: str = ""
    attachments: List[Attachment] = Field(default_factory=list, max_length=10)
    files: List[FileRef] = Field(default_factory=list, max_length=10)  # the attached files, kept for the chat to preview
    chat_settings: Optional[ChatSettings] = None
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
    pending_question: Optional[dict[str, Any]] = None  # questions the run paused to ask (status needs_input)
    usage: Optional[dict[str, Any]] = None  # tokens (and cost, when prices are set) for this reply
    citations: Optional[List[dict[str, Any]]] = None  # sources cited as [n] in the reply


class ApprovalRequest(BaseModel):
    approved: bool


class AnswerRequest(BaseModel):
    """Answers to the question cards: question text -> the chosen label(s) or the user's own words."""
    answers: dict[str, Union[str, List[str]]] = Field(min_length=1)


class AgentSession(BaseModel):
    id: int
    session_id: str
    title: str = ""
    messages: List[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class SessionPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    pinned: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("A title can't be empty")
        return value.strip() if value is not None else None


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

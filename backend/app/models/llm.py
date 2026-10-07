from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class LLMProvider(BaseModel):
    id: Optional[int] = None
    provider_name: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: bool = True


class LLMCreateRequest(BaseModel):
    provider_name: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: bool = True


class LLMUpdateRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: Optional[bool] = None


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Optional[dict[str, Any]] = None
    finish_reason: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]
    model: Optional[str] = None
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Optional[dict[str, Any]] = None
    finish_reason: Optional[str] = None

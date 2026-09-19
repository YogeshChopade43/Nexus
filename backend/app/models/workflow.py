from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    steps: Optional[List[Dict[str, Any]]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    enabled: bool = True
    isActive: Optional[bool] = None
    trigger: str = "manual"


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    enabled: Optional[bool] = None
    isActive: Optional[bool] = None
    trigger: Optional[str] = None


class WorkflowResponse(BaseModel):
    id: int
    name: str
    description: str
    steps: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    version: int = 1
    created_at: str
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    createdAt: str
    updatedAt: Optional[str] = None
    createdBy: Optional[str] = None
    enabled: bool = True
    isActive: bool = True
    trigger: str = "manual"
    last_run: Optional[str] = None


class WorkflowRunRequest(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: int
    workflowId: str
    status: str
    started_at: str = Field(default_factory=_utc_now)
    startedAt: str = Field(default_factory=_utc_now)
    completed_at: Optional[str] = None
    completedAt: Optional[str] = None
    input_data: Dict[str, Any] = Field(default_factory=dict)
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[Dict[str, Any]] = Field(default_factory=list)

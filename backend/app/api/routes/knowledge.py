"""Facts the agent remembers across chats (see app.knowledge). Documents moved to /api/rag."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app import knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


@router.get("/memories")
def memories() -> list[dict[str, Any]]:
    return knowledge.list_memories()


@router.post("/memories")
def add_memory(body: MemoryIn) -> dict[str, Any]:
    try:
        return knowledge.add_memory(body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int) -> Response:
    if not knowledge.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=204)

"""How the chat agent reaches documents: the ``nexus__search_documents`` tool and the per-turn
state that numbers sources consistently and turns ``[n]`` markers into citations."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Optional

from app.core.database import get_connection
from app.rag.access import readable_collections
from app.rag.answer import extract_citations, sources_block
from app.rag.models import DEFAULT_WORKSPACE, Hit, RetrievalResult
from app.rag.retrieve import retrieve
from app.tools.base import Tool


@dataclass
class Turn:
    """Sources gathered while answering one message, numbered 1.. in the order first seen."""
    workspace_id: int = DEFAULT_WORKSPACE
    session_id: Optional[str] = None
    sources: list[Hit] = field(default_factory=list)

    def add(self, result: RetrievalResult) -> RetrievalResult:
        """Merge a search's sources into the turn; returns them with their turn-wide numbers' order."""
        known = {hit.chunk_id: index for index, hit in enumerate(self.sources)}
        for hit in result.sources:
            if hit.chunk_id not in known:
                known[hit.chunk_id] = len(self.sources)
                self.sources.append(hit)
        return result

    def block(self, result: RetrievalResult) -> str:
        """The sources block for one search, numbered as in the whole turn."""
        if result.insufficient or not result.sources:
            return sources_block(result)
        numbers = [next(i for i, h in enumerate(self.sources, start=1) if h.chunk_id == hit.chunk_id)
                   for hit in result.sources]
        return sources_block(result, numbers)

    def cite(self, answer: str) -> tuple[str, list[dict[str, Any]]]:
        if not self.sources:
            return answer, []
        text, citations = extract_citations(answer, RetrievalResult(self.sources, False, None))
        return text, [asdict(c) for c in citations]


_turn: ContextVar[Optional[Turn]] = ContextVar("rag_turn", default=None)


@contextmanager
def rag_turn(workspace_id: int, session_id: Optional[str]) -> Iterator[Turn]:
    turn = Turn(workspace_id, session_id)
    token = _turn.set(turn)
    try:
        yield turn
    finally:
        _turn.reset(token)


def current_turn() -> Turn:
    return _turn.get() or Turn()


def readable_document_names(workspace_id: int, session_id: Optional[str], limit: int = 20) -> list[str]:
    """Names of ready documents this conversation can search (libraries + its own attachments)."""
    collections = readable_collections(workspace_id, session_id)
    if not collections:
        return []
    marks = ",".join("?" * len(collections))
    conn = get_connection()
    try:
        return [r[0] for r in conn.execute(
            f"SELECT name FROM documents WHERE status = 'ready' AND collection_id IN ({marks}) ORDER BY id DESC LIMIT ?",
            (*collections, limit))]
    finally:
        conn.close()


def has_readable_documents(workspace_id: int, session_id: Optional[str]) -> bool:
    return bool(readable_document_names(workspace_id, session_id, limit=1))


def _library_id(workspace_id: int, name: str) -> Optional[int]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM collections WHERE workspace_id = ? AND kind = 'library' AND name = ? COLLATE NOCASE",
                           (workspace_id, name.strip())).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class SearchDocuments(Tool):
    policy = "allow"
    read_only = True

    def __init__(self) -> None:
        super().__init__("nexus__search_documents", "nexus",
                         "Search the user's documents (their libraries and files attached to this chat) and return "
                         "numbered passages to cite like [1].")

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": (
                    "What to look for, as a standalone question or several keywords and synonyms. In a follow-up, "
                    "replace he/she/it/that/they with what they refer to in the conversation ('what about his "
                    "education?' after a question about Rahul's resume -> 'Rahul education degree university').")},
                "collection": {"type": "string", "description": "Optional: search only the library with this name"},
            },
            "required": ["query"],
        }

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        turn = current_turn()
        collection_ids = None
        if parameters.get("collection"):
            library = _library_id(turn.workspace_id, str(parameters["collection"]))
            collection_ids = [library] if library else []
        result = await asyncio.to_thread(retrieve, str(parameters.get("query") or ""), workspace_id=turn.workspace_id,
                                         session_id=turn.session_id, collection_ids=collection_ids)
        turn.add(result)
        return {"text": turn.block(result), "data": {"sources": [asdict(h) for h in result.sources],
                                                      "insufficient": result.insufficient, "log_id": result.log_id}}

"""Plain data passed between the RAG modules (see docs/superpowers/specs/2026-10-08-production-rag-design.md)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

DEFAULT_WORKSPACE = 1


@dataclass(frozen=True)
class Block:
    """One structural piece of a loaded file."""
    text: str
    kind: Literal["heading", "paragraph", "table"]
    level: int = 0  # heading level (1 = top); 0 for non-headings
    page: Optional[int] = None


@dataclass(frozen=True)
class LoadedDoc:
    blocks: list[Block]
    pages: Optional[int]


@dataclass(frozen=True)
class ChunkDraft:
    kind: Literal["parent", "child"]
    text: str
    heading_path: str
    page_start: Optional[int]
    page_end: Optional[int]
    char_start: int
    char_end: int
    tokens: int
    parent_index: Optional[int]  # children only: index into the parents list


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: int
    document_name: str
    text: str
    heading_path: str
    page_start: Optional[int]
    page_end: Optional[int]
    parent_id: Optional[int]
    score: float


@dataclass(frozen=True)
class Citation:
    n: int
    document_id: int
    document_name: str
    heading_path: str
    pages: str
    chunk_id: int
    snippet: str


@dataclass(frozen=True)
class RetrievalResult:
    sources: list[Hit]  # parent-level passages, numbered from 1 in this order
    insufficient: bool
    log_id: Optional[int]
    keyword_only: bool = False  # True when the embedding model was unavailable
    low_confidence: bool = False  # the reranker doubts every passage; the model must judge relevance

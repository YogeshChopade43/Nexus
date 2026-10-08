"""Structure-aware, small-to-big chunking.

Sections follow the document's headings. Each section becomes one or more **parents** (what the
model reads, ≤ 1,200 tokens) and each parent is cut into overlapping **children** (what gets
searched, ~350 tokens, 50-token overlap). Cuts prefer paragraph and sentence boundaries; tables
stay whole when they fit and otherwise split by rows with the header repeated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.rag.models import Block, ChunkDraft, LoadedDoc
from app.rag.tokens import CHARS_PER_TOKEN, count_tokens

SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s+|\n\s*\n")


def context_header(document_name: str, heading_path: str) -> str:
    """Prepended to a chunk's text before embedding and keyword indexing (not stored in the chunk)."""
    return f"{document_name} › {heading_path}\n\n" if heading_path else f"{document_name}\n\n"


@dataclass
class _Piece:
    """Text of one block (or part of one) with its page; tables are kept apart from prose."""
    text: str
    is_table: bool
    page: Optional[int]


@dataclass
class _Section:
    heading_path: str
    pieces: list[_Piece] = field(default_factory=list)


def _sections(doc: LoadedDoc) -> list[_Section]:
    stack: list[tuple[int, str]] = []
    sections = [_Section("")]
    for block in doc.blocks:
        if block.kind == "heading":
            level = block.level or 1
            stack = [(lvl, title) for lvl, title in stack if lvl < level] + [(level, block.text.strip())]
            sections.append(_Section(" › ".join(title for _, title in stack)))
        elif block.text.strip():
            sections[-1].pieces.append(_Piece(block.text.strip(), block.kind == "table", block.page))
    return [s for s in sections if s.pieces]


def _split_table(text: str, max_chars: int) -> list[str]:
    """Row groups of at most max_chars, each starting with the header row."""
    lines = text.split("\n")
    header, rows = lines[0], lines[1:]
    groups, current = [], [header]
    for row in rows:
        if len(current) > 1 and len("\n".join(current + [row])) > max_chars:
            groups.append("\n".join(current))
            current = [header]
        current.append(row)
    groups.append("\n".join(current))
    return groups


def _cut_point(text: str, start: int, limit: int) -> int:
    """End of a window starting at ``start`` no longer than ``limit``: a sentence or paragraph end
    in the second half of the window, else the last whitespace there, else a hard cut."""
    end = start + limit
    if end >= len(text):
        return len(text)
    window_start = start + limit // 2
    best = -1
    for match in SENTENCE_END.finditer(text, window_start, end):
        best = match.end()
    if best > 0:
        return best
    space = text.rfind(" ", window_start, end)
    return space + 1 if space > 0 else end


def _windows(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """(start, end) spans of at most ``size`` chars; each next span begins about ``overlap`` chars
    before the previous end, at a sentence start when there is one."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = _cut_point(text, start, size)
        spans.append((start, end))
        if end >= len(text):
            break
        target = end - overlap
        next_start = -1
        for match in SENTENCE_END.finditer(text, max(start + 1, target - overlap), target + 1):
            next_start = match.end()  # the last sentence start at or before the target
        if next_start <= start:
            space = text.rfind(" ", start + 1, target + 1)
            next_start = space + 1 if space > start else target
        start = max(next_start, start + 1)
    return spans


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _pages(spans: list[tuple[int, int, Optional[int]]], start: int, end: int) -> tuple[Optional[int], Optional[int]]:
    pages = [page for s, e, page in spans if page is not None and s < end and e > start]
    return (min(pages), max(pages)) if pages else (None, None)


def chunk(doc: LoadedDoc, *, parent_tokens: int = 1200, child_tokens: int = 350,
          overlap_tokens: int = 50) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    parent_chars = parent_tokens * CHARS_PER_TOKEN
    child_chars = child_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    parents: list[ChunkDraft] = []
    children: list[ChunkDraft] = []
    doc_offset = 0

    for section in _sections(doc):
        # Oversized pieces are split first so every parent fits.
        pieces: list[_Piece] = []
        for piece in section.pieces:
            if len(piece.text) <= parent_chars:
                pieces.append(piece)
            elif piece.is_table:
                pieces.extend(_Piece(t, True, piece.page) for t in _split_table(piece.text, parent_chars))
            else:
                pieces.extend(_Piece(piece.text[s:e].strip(), False, piece.page)
                              for s, e in _windows(piece.text, parent_chars, 0) if piece.text[s:e].strip())

        # Group pieces into parents.
        groups: list[list[_Piece]] = [[]]
        for piece in pieces:
            current = groups[-1]
            size = sum(len(p.text) + 2 for p in current)
            if current and size + len(piece.text) > parent_chars:
                groups.append([piece])
            else:
                current.append(piece)

        for group in groups:
            if not group:
                continue
            # Parent text, remembering where each piece sits in it.
            spans: list[tuple[int, int, Optional[int]]] = []
            parts, offset = [], 0
            for piece in group:
                spans.append((offset, offset + len(piece.text), piece.page))
                parts.append(piece.text)
                offset += len(piece.text) + 2
            parent_text = "\n\n".join(parts)
            page_start, page_end = _pages(spans, 0, len(parent_text))
            parent_index = len(parents)
            parents.append(ChunkDraft("parent", parent_text, section.heading_path, page_start, page_end,
                                      doc_offset, doc_offset + len(parent_text), count_tokens(parent_text), None))

            def add_child(text: str, start: int, end: int) -> None:
                first, last = _pages(spans, start, end)
                children.append(ChunkDraft("child", text, section.heading_path, first, last,
                                           doc_offset + start, doc_offset + end, count_tokens(text), parent_index))

            # Children: prose runs get sliding windows; tables stay whole or split by rows.
            run_start = None
            for index, (piece, (s, e, _)) in enumerate(zip(group, spans)):
                if not piece.is_table and run_start is None:
                    run_start = s
                is_last = index == len(group) - 1
                if run_start is not None and (piece.is_table or is_last):
                    run_end = s - 2 if piece.is_table else e
                    for ws, we in _windows(parent_text[run_start:run_end], child_chars, overlap_chars):
                        a, b = _strip_span(parent_text, run_start + ws, run_start + we)
                        if b > a:
                            add_child(parent_text[a:b], a, b)
                    run_start = None
                if piece.is_table:
                    tables = [piece.text] if len(piece.text) <= child_chars else _split_table(piece.text, child_chars)
                    for table in tables:
                        add_child(table, s, e)
            doc_offset += len(parent_text) + 2
    return parents, children

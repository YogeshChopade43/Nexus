"""RAG Task 3: structure-aware, small-to-big chunking."""
from __future__ import annotations

import time

from app.rag.chunking import chunk, context_header
from app.rag.models import Block, LoadedDoc
from app.rag.tokens import count_tokens


def sentences(n: int, word: str = "alpha") -> str:
    return " ".join(f"Sentence {i} talks about {word} and more words here." for i in range(n))


def test_count_tokens():
    assert count_tokens("") == 1 and count_tokens("abcdefgh") == 2


def test_heading_paths():
    doc = LoadedDoc([
        Block("Handbook", "heading", 1), Block("Leave", "heading", 2), Block("Parental", "heading", 3),
        Block("Twelve weeks of leave.", "paragraph"),
        Block("Pay", "heading", 2), Block("Paid monthly.", "paragraph"),
    ], None)
    parents, children = chunk(doc)
    paths = {c.text: c.heading_path for c in children}
    assert paths["Twelve weeks of leave."] == "Handbook › Leave › Parental"
    assert paths["Paid monthly."] == "Handbook › Pay"  # a later H2 resets deeper levels


def test_sizes_and_overlap():
    doc = LoadedDoc([Block("Big", "heading", 1), Block(sentences(400), "paragraph")], None)
    parents, children = chunk(doc)
    assert all(p.tokens <= 1200 for p in parents)
    assert all(c.tokens <= 360 for c in children)
    for a, b in zip(children, children[1:]):
        if a.parent_index == b.parent_index:
            overlap = a.text[-160:]  # ~40 tokens
            assert overlap[-40:] in b.text, "consecutive children of one parent must overlap"
    for c in children:
        assert c.text == c.text.strip() and not c.text[0].isspace()
        assert c.text.split()[0].isalnum() or c.text[0].isupper() or c.text[0].isdigit()  # never a mid-word start


def test_tables_kept_whole():
    small = "h1 | h2\n" + "\n".join(f"a{i} | b{i}" for i in range(40))  # ~200 tokens
    parents, children = chunk(LoadedDoc([Block(small, "table")], None))
    assert [c.text for c in children] == [small]

    big = "name | value\n" + "\n".join(f"row number {i} | value {i} with text" for i in range(110))  # ~900 tokens
    parents, children = chunk(LoadedDoc([Block(big, "table")], None))
    assert len(children) > 1
    assert all(c.text.splitlines()[0] == "name | value" for c in children)


def test_pages_tracked():
    doc = LoadedDoc([Block("On page three.", "paragraph", page=3), Block("On page four.", "paragraph", page=4)], 4)
    _, children = chunk(doc)
    assert children[0].page_start == 3 and children[0].page_end == 4


def test_children_point_to_parents():
    doc = LoadedDoc([Block("A", "heading", 1), Block(sentences(300, "beta"), "paragraph"),
                     Block("B", "heading", 1), Block(sentences(50, "gamma"), "paragraph")], None)
    parents, children = chunk(doc)
    for c in children:
        assert 0 <= c.parent_index < len(parents)
        assert c.text in parents[c.parent_index].text


def test_no_whitespace_text():
    blob = "x" * 2_000_000
    started = time.time()
    _, children = chunk(LoadedDoc([Block(blob, "paragraph")], None))
    assert time.time() - started < 2
    assert all(c.tokens <= 350 for c in children)
    assert sum(len(c.text) for c in children) >= len(blob)


def test_context_header():
    assert context_header("Handbook.pdf", "Leave › Parental") == "Handbook.pdf › Leave › Parental\n\n"
    assert context_header("notes.txt", "") == "notes.txt\n\n"

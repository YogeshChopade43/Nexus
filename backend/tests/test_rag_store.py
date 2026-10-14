"""RAG Task 5: SQLite store (collections, documents, chunks, keyword and vector indexes)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.rag import store
from app.rag.chunking import chunk
from app.rag.embeddings import embed_cached
from app.rag.loaders import load


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def index(document: dict, text: str) -> None:
    """Chunk, embed and store ``text`` for ``document`` the way ingestion will."""
    parents, children = chunk(load("doc.md", text.encode()))
    vectors = embed_cached([c.text for c in children])
    conn = store.connect()
    try:
        store.replace_chunks(conn, document["id"], parents, children, vectors, document["name"])
        store.set_status(document["id"], "ready", conn=conn)
        conn.commit()
    finally:
        conn.close()


def library(name: str, workspace_id: int = 1) -> dict:
    return store.create_collection(workspace_id, name)


def test_dedupe_same_hash(client):
    a, b = library("dedupe A"), library("dedupe B")
    first, created = store.create_document(1, a["id"], "x.txt", "text/plain", b"same bytes")
    again, created_again = store.create_document(1, a["id"], "x.txt", "text/plain", b"same bytes")
    assert created and not created_again and again["id"] == first["id"]
    other, created_other = store.create_document(1, b["id"], "x.txt", "text/plain", b"same bytes")
    assert created_other and other["id"] != first["id"]


def test_new_version_replaces_old_chunks(client):
    lib = library("versions")
    v1, _ = store.create_document(1, lib["id"], "notes.md", "text/markdown", b"v1")
    index(v1, "# Notes\n\nThe zebra protocol is retired.")
    assert store.keyword_search(1, [lib["id"]], "zebra")
    v2, _ = store.create_document(1, lib["id"], "notes.md", "text/markdown", b"v2")
    assert v2["version"] == 2
    index(v2, "# Notes\n\nThe falcon protocol replaced it.")
    assert not store.keyword_search(1, [lib["id"]], "zebra")
    assert store.keyword_search(1, [lib["id"]], "falcon")


def test_keyword_and_vector_search_scoped(client):
    a, b = library("scope A"), library("scope B")
    doc_a, _ = store.create_document(1, a["id"], "a.md", "text/markdown", b"a")
    doc_b, _ = store.create_document(1, b["id"], "b.md", "text/markdown", b"b")
    index(doc_a, "# A\n\nPenguins live in Antarctica.")
    index(doc_b, "# B\n\nPenguins also appear in zoos.")
    assert {h.document_id for h in store.keyword_search(1, [a["id"]], "penguins")} == {doc_a["id"]}
    vector = embed_cached(["penguins"])[0]
    assert {h.document_id for h in store.vector_search(1, [a["id"]], vector)} == {doc_a["id"]}
    # Another workspace never sees workspace 1's data.
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO workspaces (id, name) VALUES (2, 'Other')")
    conn.commit()
    conn.close()
    assert store.keyword_search(2, [a["id"]], "penguins") == []
    assert store.vector_search(2, [a["id"]], vector) == []


def test_delete_cascades(client):
    lib = library("delete")
    doc, _ = store.create_document(1, lib["id"], "gone.md", "text/markdown", b"gone")
    index(doc, "# Gone\n\nEphemeral words here.")
    store.delete_document(doc["id"])
    conn = store.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM document_files WHERE document_id = ?", (doc["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunk_fts WHERE text LIKE '%ephemeral%'").fetchone()[0] == 0
        assert store.vector_search(1, [lib["id"]], embed_cached(["ephemeral"])[0]) == []
    finally:
        conn.close()


def test_python_fallback(client, monkeypatch):
    monkeypatch.setattr(store, "_backend", "python")
    conn = store.connect()
    store.ensure_vector_table(conn)
    conn.close()
    lib = library("fallback")
    doc, _ = store.create_document(1, lib["id"], "f.md", "text/markdown", b"f")
    index(doc, "# F\n\n## One\n\nOrchids need humidity.\n\n## Two\n\nCacti need sun.")
    hits = store.vector_search(1, [lib["id"]], embed_cached(["orchids humidity"])[0])
    assert hits[0].text.startswith("Orchids")


def test_collection_limit(client, monkeypatch):
    monkeypatch.setattr(store, "MAX_DOCUMENTS_PER_COLLECTION", 2)
    lib = library("limit")
    store.create_document(1, lib["id"], "1.txt", "text/plain", b"1")
    store.create_document(1, lib["id"], "2.txt", "text/plain", b"2")
    with pytest.raises(ValueError, match="2 documents"):
        store.create_document(1, lib["id"], "3.txt", "text/plain", b"3")


def test_chat_collection_get_or_create(client):
    first = store.chat_collection(1, "session-xyz")
    assert store.chat_collection(1, "session-xyz")["id"] == first["id"] and first["kind"] == "chat"
    assert all(c["kind"] == "library" for c in store.list_collections(1))


def test_parents_and_neighbours(client):
    lib = library("neighbours")
    doc, _ = store.create_document(1, lib["id"], "n.md", "text/markdown", b"n")
    index(doc, "# N\n\n" + " ".join(f"Sentence {i} about lanterns." for i in range(300)))
    hit = store.keyword_search(1, [lib["id"]], "lanterns")[0]
    parent = store.parents_of([hit.chunk_id])[hit.chunk_id]
    assert hit.text in parent.text and parent.parent_id is None
    view = store.get_chunk_with_neighbours(hit.chunk_id)
    assert view["chunk"]["id"] == hit.chunk_id and "document_name" in view["chunk"]


def test_move_keeps_document_searchable_in_new_collection(client):
    a, b = library("move from"), library("move to")
    doc, _ = store.create_document(1, a["id"], "m.md", "text/markdown", b"m")
    index(doc, "# M\n\nMarmots whistle loudly.")
    store.move_document(doc["id"], b["id"])
    vector = embed_cached(["marmots whistle"])[0]
    assert store.vector_search(1, [a["id"]], vector) == []
    assert {h.document_id for h in store.vector_search(1, [b["id"]], vector)} == {doc["id"]}
    assert {h.document_id for h in store.keyword_search(1, [b["id"]], "marmots")} == {doc["id"]}

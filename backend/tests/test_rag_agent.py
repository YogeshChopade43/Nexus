"""RAG Task 10: the agent's document tool, automatic retrieval from a library, citations,
per-chat collections and the import of documents from the old keyword-only system."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.agent.sessions import get_session
from app.core.database import get_connection
from app.main import app
from app.rag import ingest, legacy, store
from tests.test_chatbot import ScriptedLLM


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def llm(monkeypatch):
    fake = ScriptedLLM()
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (fake, {}))
    return fake


def ready(document: dict) -> dict:
    deadline = time.time() + 10
    while time.time() < deadline:
        current = store.get_document(document["id"])
        if current["status"] in ("ready", "failed"):
            return current
        time.sleep(0.05)
    raise AssertionError("not ready")


def session(client) -> str:
    return client.post("/api/agent/sessions", json={}).json()["session_id"]


def tool_calls(llm):
    return [c for c in llm.calls if c["kind"] == "tools"]


def test_tool_offered_only_with_readable_documents(client, llm):
    conn = get_connection()
    has_docs = conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'ready'").fetchone()[0]
    conn.close()
    sid = session(client)
    client.post("/api/agent/run", json={"message": "hello", "session_id": sid})
    offered = any("nexus__search_documents" in c["tools"] for c in tool_calls(llm))
    assert offered == bool(has_docs)

    lib = store.create_collection(1, "Agent policies")
    ready(ingest.submit(1, lib["id"], "shipping.md", b"# Shipping\n\nShipping to Pune takes 5 business days."))
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "hello again", "session_id": sid})
    first = tool_calls(llm)[0]
    assert "nexus__search_documents" in first["tools"]
    assert "shipping.md" in first["messages"][0]["content"]  # the hint names the readable documents


def test_tool_returns_numbered_sources_and_citations(client, llm):
    llm.script = lambda m, t: (
        {"content": "Shipping takes 5 days [1]. Also [9].", "tool_calls": []} if m[-1]["role"] == "tool"
        else ("nexus__search_documents", {"query": "shipping time Pune"}))
    r = client.post("/api/agent/run", json={"message": "how long is shipping?", "session_id": session(client)}).json()
    tool_output = next(m for m in tool_calls(llm)[-1]["messages"] if m["role"] == "tool")["content"]
    assert "<sources>" in tool_output and "[1] shipping.md" in tool_output
    assert r["response"] == "Shipping takes 5 days [1]. Also."
    assert [c["document_name"] for c in r["citations"]] == ["shipping.md"] and "rag_log_id" not in r


def test_automatic_retrieval_with_attached_library(client, llm):
    lib = store.create_collection(1, "Auto library")
    ready(ingest.submit(1, lib["id"], "returns.md", b"# Returns\n\nRefunds are accepted within 30 days."))
    llm.script = lambda m, t: {"content": "You have 30 days [1].", "tool_calls": []}
    sid = session(client)
    r = client.post("/api/agent/run", json={"message": "what is the refund window?", "session_id": sid,
                                            "chat_settings": {"library_id": lib["id"]}}).json()
    system = (tool_calls(llm) or [c for c in llm.calls])[0]["messages"][0]["content"]
    assert "<sources>" in system and "[1] returns.md" in system
    assert r["citations"][0]["document_name"] == "returns.md"
    stored = get_session(sid)["messages"][-1]
    assert stored["citations"][0]["n"] == 1 and "rag_log_id" not in stored


def test_chat_attachment_scope(client, llm):
    chat_x, chat_y = session(client), session(client)
    collection = store.chat_collection(1, chat_x)
    ready(ingest.submit(1, collection["id"], "private.md", b"# Private\n\nThe locker code is otter."))
    llm.script = lambda m, t: (
        {"content": m[-1]["content"][:300], "tool_calls": []} if m[-1]["role"] == "tool"
        else ("nexus__search_documents", {"query": "locker code otter"}))
    in_x = client.post("/api/agent/run", json={"message": "locker?", "session_id": chat_x}).json()
    in_y = client.post("/api/agent/run", json={"message": "locker?", "session_id": chat_y}).json()
    assert "otter" in in_x["response"] and "otter" not in in_y["response"]


def test_delete_conversation_deletes_chat_collection(client):
    sid = session(client)
    collection = store.chat_collection(1, sid)
    doc = ready(ingest.submit(1, collection["id"], "temp.md", b"# T\n\ntemporary"))
    assert client.delete(f"/api/agent/sessions/{sid}").status_code == 200
    assert store.get_collection(collection["id"]) is None and store.get_document(doc["id"]) is None


def test_legacy_import(client):
    text = ("Jane Doe, AI Engineer. " * 80).strip()
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS legacy_documents (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, chars INTEGER, "
                 "chunks INTEGER, session_id TEXT, created_at TEXT)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS legacy_document_chunks USING fts5(doc_id UNINDEXED, name UNINDEXED, "
                 "position UNINDEXED, content)")
    doc_id = conn.execute("INSERT INTO legacy_documents (name, chars, chunks, created_at) VALUES ('cv.pdf', ?, 2, 'now')",
                          (len(text),)).lastrowid
    # The old chunker: 1,200-char windows overlapping by 200.
    conn.execute("INSERT INTO legacy_document_chunks VALUES (?, 'cv.pdf', 0, ?)", (doc_id, text[:1200]))
    conn.execute("INSERT INTO legacy_document_chunks VALUES (?, 'cv.pdf', 1, ?)", (doc_id, text[1000:]))
    conn.commit()
    conn.close()

    assert legacy.import_legacy_documents() == 1
    imported = next(c for c in store.list_collections(1) if c["name"] == "Imported")
    doc = ready(store.list_documents(imported["id"])[0])
    assert doc["name"] == "cv.pdf" and doc["status"] == "ready" and doc["chars"] == len(text)
    assert legacy.import_legacy_documents() == 0
    conn = get_connection()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert "legacy_documents" not in tables and "legacy_document_chunks" not in tables

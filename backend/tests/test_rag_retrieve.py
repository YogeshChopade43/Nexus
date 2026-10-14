"""RAG Task 7: hybrid retrieval (keyword ∥ vector → RRF → rerank → diversity → parent budget)."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.rag import access, embeddings, ingest, retrieve as retrieval, store
from app.rag.retrieve import retrieve, rrf


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def add(collection_id: int, name: str, text: str) -> dict:
    doc = ingest.submit(store.user_workspace(), collection_id, name, text.encode())
    deadline = time.time() + 10
    while time.time() < deadline:
        current = store.get_document(doc["id"])
        if current["status"] in ("ready", "failed"):
            assert current["status"] == "ready", current
            return current
        time.sleep(0.05)
    raise AssertionError("not ready")


def test_rrf_math():
    fused = rrf([[1, 2, 3], [3, 1]])
    assert [cid for cid, _ in fused] == [1, 3, 2]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_hybrid_ranks_exact_ids_and_wording_variants(client):
    lib = store.create_collection(store.user_workspace(), "retrieve hybrid")
    add(lib["id"], "errors.md", "# Errors\n\nError code E-4012 means the token expired.")
    add(lib["id"], "returns.md", "# Returns\n\nRefunds are accepted within 30 days of delivery.")
    top = retrieve("E-4012", collection_ids=[lib["id"]]).sources[0]
    assert top.document_name == "errors.md"
    # "refund" vs "refunds": stemming on the keyword side, shared words on the vector side.
    result = retrieve("refund", collection_ids=[lib["id"]])
    assert result.sources[0].document_name == "returns.md"
    log = get_connection().execute("SELECT candidates_json FROM retrieval_logs WHERE id = ?", (result.log_id,)).fetchone()
    candidates = json.loads(log[0])
    assert any(c["keyword_rank"] is not None for c in candidates) and any(c["vector_rank"] is not None for c in candidates)


def test_diversity_cap(client):
    lib = store.create_collection(store.user_workspace(), "retrieve diversity")
    add(lib["id"], "repeat.md", "# Lighthouse\n\n" + " ".join(f"The lighthouse keeper logs entry {i}." for i in range(400)))
    add(lib["id"], "other.md", "# Other\n\nThe old lighthouse keeper retired to the harbour.")
    result = retrieve("lighthouse keeper", collection_ids=[lib["id"]])
    assert "other.md" in {s.document_name for s in result.sources}


def test_parent_expansion_budget(client):
    lib = store.create_collection(store.user_workspace(), "retrieve budget")
    for i in range(6):
        add(lib["id"], f"part{i}.md", f"# Part {i}\n\n" + " ".join(f"Quartz fact {i}-{j} is noted." for j in range(250)))
    result = retrieve("quartz fact", collection_ids=[lib["id"]], budget_tokens=3000)
    from app.rag.tokens import count_tokens

    assert sum(count_tokens(s.text) for s in result.sources) <= 3000
    assert len({s.chunk_id for s in result.sources}) == len(result.sources)  # de-duplicated
    assert all(s.parent_id is None for s in result.sources)  # parents, not children


def test_low_confidence_keeps_fused_order_and_flags(client):
    lib = store.create_collection(store.user_workspace(), "retrieve no answer")
    add(lib["id"], "garden.md", "# Garden\n\nTomatoes need sun and water.")
    # Vector search always returns something; the reranker scores it below 0.2.
    unsure = retrieve("quantum chromodynamics lattice", collection_ids=[lib["id"]])
    assert unsure.low_confidence is True and unsure.insufficient is False and unsure.sources
    sure = retrieve("tomatoes need sun", collection_ids=[lib["id"]])
    assert sure.low_confidence is False and sure.sources[0].document_name == "garden.md"
    empty = store.create_collection(store.user_workspace(), "retrieve empty")
    nothing = retrieve("tomatoes", collection_ids=[empty["id"]])
    assert nothing.insufficient is True and nothing.sources == []  # searched, found nothing
    client.patch("/api/settings/user", json={"ragRerank": False})
    try:
        assert retrieve("quantum chromodynamics", collection_ids=[lib["id"]]).low_confidence is False  # no reranker
    finally:
        client.patch("/api/settings/user", json={"ragRerank": True})


def test_scope(client):
    chat_x = store.chat_collection(store.user_workspace(), "retrieve-chat-x")
    add(chat_x["id"], "private.md", "# Private\n\nThe vault password is walrus.")
    names = lambda result: {s.document_name for s in result.sources}  # noqa: E731
    assert "private.md" in names(retrieve("vault walrus", session_id="retrieve-chat-x"))
    # Other chats (and library-only searches) may get unrelated library passages, never this file.
    assert "private.md" not in names(retrieve("vault walrus", session_id="retrieve-chat-y"))
    assert "private.md" not in names(retrieve("vault walrus"))
    assert chat_x["id"] in access.readable_collections(store.user_workspace(), "retrieve-chat-x")
    assert chat_x["id"] not in access.readable_collections(store.user_workspace(), "retrieve-chat-y")


def test_degenerate_queries(client):
    for query in ["", "?!.", '"*" OR (', "   "]:
        result = retrieve(query)
        assert isinstance(result.sources, list)


def test_log_written(client):
    result = retrieve("tomatoes")
    row = get_connection().execute("SELECT query, latency_ms_json FROM retrieval_logs WHERE id = ?", (result.log_id,)).fetchone()
    assert row["query"] == "tomatoes" and {"keyword", "vector", "rerank"} <= set(json.loads(row["latency_ms_json"]))


def test_queries_are_not_stored_in_the_embedding_cache(client):
    def cached():
        return get_connection().execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]

    lib = store.create_collection(store.user_workspace(), "retrieve cache")
    add(lib["id"], "cache.md", "# Cache\n\nThe kettle whistles at noon.")
    before = cached()
    result = retrieve("a question nobody asked before zebra-17", collection_ids=[lib["id"]])
    assert result.sources  # the search really ran (vector side returns the closest passage)
    assert cached() == before  # document vectors are cached; one-off questions are not


def test_keyword_only_when_model_unavailable(client, monkeypatch):
    def broken(query):
        raise RuntimeError("model missing")

    monkeypatch.setattr(retrieval, "_embed_query", broken)
    result = retrieve("tomatoes sun")
    assert result.keyword_only is True and result.sources


def test_reranker_failure_falls_back(client, monkeypatch):
    class Broken:
        def score(self, query, texts):
            raise RuntimeError("rerank crashed")

    monkeypatch.setattr(retrieval, "get_reranker", lambda: Broken())
    assert retrieve("tomatoes sun").sources

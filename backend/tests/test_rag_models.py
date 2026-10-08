"""RAG Task 4: local embeddings (with cache) and reranking."""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag import embeddings, rerank


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_fake_embedder_similarity():
    e = embeddings.FakeEmbedder()
    q, same, other = e.embed(["refund policy for returns", "our refund policy", "shipping to Pune"])
    assert cos(q, same) > cos(q, other)


def test_vectors_normalised():
    for v in embeddings.FakeEmbedder().embed(["a b c", "something else entirely"]):
        assert len(v) == 384 and abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-6


def test_cache_hits(client, monkeypatch):
    calls = []
    real = embeddings.FakeEmbedder.embed

    def spy(self, texts):
        calls.append(list(texts))
        return real(self, texts)

    monkeypatch.setattr(embeddings.FakeEmbedder, "embed", spy)
    first = embeddings.embed_cached(["cache me a b", "cache me a b", "cache me c"])
    assert calls == [["cache me a b", "cache me c"]]
    assert first[0] == first[1]
    calls.clear()
    embeddings.embed_cached(["cache me a b", "cache me c"])
    assert calls == []


def test_get_embedder_is_fake_in_tests():
    assert embeddings.get_embedder().model_id == "fake-hash-384"
    assert embeddings.get_embedder().dim == 384


def test_rerank_setting(client):
    assert isinstance(rerank.get_reranker(), rerank.FakeReranker)
    client.patch("/api/settings/user", json={"ragRerank": False})
    try:
        assert isinstance(rerank.get_reranker(), rerank.NoReranker)
        assert rerank.get_reranker().score("q", ["a"]) == []
    finally:
        client.patch("/api/settings/user", json={"ragRerank": True})


def test_fake_reranker_scores_word_overlap():
    scores = rerank.FakeReranker().score("capital of france", ["paris is the capital of france", "bananas are yellow"])
    assert scores[0] > scores[1] and all(0 <= s <= 1 for s in scores)


def test_models_ready_with_fakes():
    assert embeddings.models_ready()


@pytest.mark.slow
def test_real_models():
    vector = embeddings.FastEmbedEmbedder().embed(["hello world"])[0]
    assert len(vector) == 384
    scores = rerank.FastEmbedReranker().score("capital of France",
                                              ["Paris is the capital of France", "Bananas are yellow"])
    assert scores[0] > scores[1]

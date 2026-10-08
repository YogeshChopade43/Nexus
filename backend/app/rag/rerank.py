"""Reranking: a local cross-encoder re-scores (query, passage) pairs for relevance (0–1).

On by default; the ``ragRerank`` user setting turns it off. ``NEXUS_RAG_RERANKER=fake`` swaps in a
word-overlap scorer for tests.
"""
from __future__ import annotations

import math
import os
import re
import threading
from typing import Protocol

DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class NoReranker:
    """Reranking off: callers keep the fused order."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        return []


def _stems(text: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"\w+", text.lower())}


class FakeReranker:
    """Share of the query's words (plural-insensitive) found in the passage. For tests only."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        words = _stems(query)
        if not words:
            return [0.0 for _ in texts]
        return [len(words & _stems(t)) / len(words) for t in texts]


class FastEmbedReranker:
    """``Xenova/ms-marco-MiniLM-L-6-v2``; downloads (~90 MB) into data/models on first use."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self.ready = False

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                from app.rag.embeddings import models_dir

                self._model = TextCrossEncoder(model_name=self.model_name, cache_dir=str(models_dir()))
                self.ready = True

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        self.load()
        return [1 / (1 + math.exp(-float(logit))) for logit in self._model.rerank(query, texts)]


_reranker: Reranker | None = None


def _model_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = FakeReranker() if os.getenv("NEXUS_RAG_RERANKER") == "fake" else FastEmbedReranker()
    return _reranker


def rerank_enabled() -> bool:
    from app.api.routes.settings import load_user_settings

    return bool(load_user_settings().get("ragRerank", True))


def get_reranker() -> Reranker:
    return _model_reranker() if rerank_enabled() else NoReranker()


def reranker_ready() -> bool:
    return not rerank_enabled() or bool(getattr(_model_reranker(), "ready", True))

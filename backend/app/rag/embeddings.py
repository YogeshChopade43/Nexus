"""Text embeddings, computed locally (fastembed + ONNX on the CPU), with a content-addressed cache.

``NEXUS_RAG_EMBEDDER=fake`` swaps in a deterministic hashing embedder so tests need no model.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
from array import array
from pathlib import Path
from typing import Protocol

from app.core.database import get_connection, get_db_path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
BATCH = 64


def models_dir() -> Path:
    """Where models are downloaded: NEXUS_MODELS_DIR, else ``models`` next to the database."""
    path = Path(os.getenv("NEXUS_MODELS_DIR") or get_db_path().parent / "models")
    path.mkdir(parents=True, exist_ok=True)
    return path


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class FakeEmbedder:
    """Bag-of-words hashed into 384 buckets: texts sharing words are close. For tests only."""
    model_id = "fake-hash-384"
    dim = DIM
    ready = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * DIM
            for word in re.findall(r"\w+", text.lower()):
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
            vectors.append(_normalise(vector) if any(vector) else [1.0 / math.sqrt(DIM)] * DIM)
        return vectors


class FastEmbedEmbedder:
    """``BAAI/bge-small-en-v1.5``; downloads (~130 MB) into data/models on first use."""
    dim = DIM

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_id = model_name
        self._model = None
        self._lock = threading.Lock()
        self.ready = False

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model_id, cache_dir=str(models_dir()))
                self.ready = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.load()
        return [_normalise([float(x) for x in v]) for v in self._model.embed(texts, batch_size=BATCH)]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = FakeEmbedder() if os.getenv("NEXUS_RAG_EMBEDDER") == "fake" else FastEmbedEmbedder()
    return _embedder


def models_ready() -> bool:
    """True when the search models can be used without a download (always, for the fakes)."""
    from app.rag.rerank import reranker_ready

    return bool(getattr(get_embedder(), "ready", False)) and reranker_ready()


def prepare_models() -> bool:
    """Load (downloading on first use) the embedding and rerank models; False if that isn't possible
    right now, e.g. offline before the first download."""
    from app.rag.rerank import _model_reranker, rerank_enabled

    try:
        for model in (get_embedder(), _model_reranker() if rerank_enabled() else None):
            if model is not None and hasattr(model, "load"):
                model.load()
    except Exception as exc:
        logger.warning("Search models aren't available yet: %s", exc)
        return False
    return models_ready()


def _key(model_id: str, text: str) -> str:
    return hashlib.sha256(f"{model_id}\n{text}".encode()).hexdigest()


def embed_cached(texts: list[str]) -> list[list[float]]:
    """Embed ``texts``, reusing vectors already computed for the same model and text."""
    embedder = get_embedder()
    keys = [_key(embedder.model_id, t) for t in texts]
    found: dict[str, list[float]] = {}
    conn = get_connection()
    try:
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), 500):
            batch = unique[start:start + 500]
            marks = ",".join("?" * len(batch))
            for row in conn.execute(f"SELECT key, vector FROM embedding_cache WHERE key IN ({marks})", batch):
                found[row["key"]] = list(array("f", row["vector"]))
        missing = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in found))
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            vectors = embedder.embed(batch)
            rows = []
            for text, vector in zip(batch, vectors):
                key = _key(embedder.model_id, text)
                found[key] = vector
                rows.append((key, array("f", vector).tobytes()))
            conn.executemany("INSERT OR REPLACE INTO embedding_cache (key, vector) VALUES (?, ?)", rows)
            conn.commit()
    finally:
        conn.close()
    return [found[k] for k in keys]

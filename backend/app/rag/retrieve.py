"""Hybrid retrieval: keyword (BM25) ∥ vector search → Reciprocal Rank Fusion → rerank → diversity
→ parent sections within a token budget → "documents don't cover this" threshold. Every search is
logged with per-stage timings."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.core.database import get_connection
from app.rag import store
from app.rag.access import readable_collections
from app.rag.embeddings import get_embedder
from app.rag.models import DEFAULT_WORKSPACE, Hit, RetrievalResult
from app.rag.rerank import get_reranker
from app.rag.tokens import count_tokens

logger = logging.getLogger(__name__)

CANDIDATES = 40
RRF_K = 60
MAX_PER_PARENT = 3
DIVERSITY_MARGIN = 0.05
# Below this best rerank score the reranker is unsure. Measured on the golden set it can't tell hard
# paraphrases from unanswerable questions, so retrieval doesn't refuse: it keeps the fused order and
# marks the result low-confidence, and the answering model decides (see answer.LOW_CONFIDENCE).
NO_ANSWER_THRESHOLD = 0.2


def _embed_query(query: str) -> list[float]:
    """Questions are embedded fresh: caching them (unlike document passages) would grow the
    database with every question asked."""
    return get_embedder().embed([query])[0]


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])


def _diverse(ordered: list[tuple[Hit, float]], keep: int) -> list[tuple[Hit, float]]:
    """At most MAX_PER_PARENT children per parent section; when two candidates score within
    DIVERSITY_MARGIN, prefer one from a document not chosen yet."""
    chosen: list[tuple[Hit, float]] = []
    per_parent: dict[int, int] = {}
    remaining = list(ordered)
    while remaining and len(chosen) < keep:
        documents = {h.document_id for h, _ in chosen}
        best_hit, best_score = remaining[0]
        pick = 0
        if best_hit.document_id in documents:
            for index, (hit, score) in enumerate(remaining[1:], start=1):
                if score < best_score - abs(best_score) * DIVERSITY_MARGIN:
                    break
                if hit.document_id not in documents:
                    pick = index
                    break
        hit, score = remaining.pop(pick)
        parent = hit.parent_id or hit.chunk_id
        if per_parent.get(parent, 0) >= MAX_PER_PARENT:
            continue
        per_parent[parent] = per_parent.get(parent, 0) + 1
        chosen.append((hit, score))
    return chosen


def _log(workspace_id: int, session_id: Optional[str], query: str, collection_ids: list[int], candidates: list[dict],
         selected: list[int], timings: dict[str, float]) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO retrieval_logs (workspace_id, session_id, query, filters_json, candidates_json, selected_json, "
            "latency_ms_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (workspace_id, session_id, query, json.dumps({"collection_ids": collection_ids}), json.dumps(candidates),
             json.dumps(selected), json.dumps(timings),
             datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def retrieve(query: str, *, workspace_id: int = DEFAULT_WORKSPACE, session_id: Optional[str] = None,
             collection_ids: Optional[list[int]] = None, budget_tokens: int = 3000, keep: int = 8) -> RetrievalResult:
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[stage] = round((now - clock) * 1000, 1)
        clock = now

    scope = readable_collections(workspace_id, session_id, collection_ids)
    query = (query or "").strip()
    if not query or not scope:
        return RetrievalResult([], False, _log(workspace_id, session_id, query, scope, [], [], timings))

    keyword = store.keyword_search(workspace_id, scope, query, CANDIDATES)
    lap("keyword")
    keyword_only = False
    try:
        vector = store.vector_search(workspace_id, scope, _embed_query(query), CANDIDATES)
    except Exception as exc:
        logger.warning("Vector search unavailable, using keywords only: %s", exc)
        vector, keyword_only = [], True
    lap("vector")

    hits = {h.chunk_id: h for h in keyword + vector}
    keyword_rank = {h.chunk_id: i for i, h in enumerate(keyword, start=1)}
    vector_rank = {h.chunk_id: i for i, h in enumerate(vector, start=1)}
    fused = rrf([[h.chunk_id for h in keyword], [h.chunk_id for h in vector]])[:CANDIDATES]
    lap("fusion")

    candidates = [hits[cid] for cid, _ in fused]
    try:
        scores = get_reranker().score(query, [h.text for h in candidates]) if candidates else []
    except Exception as exc:
        logger.warning("Reranking failed, keeping fused order: %s", exc)
        scores = []
    lap("rerank")
    low_confidence = bool(scores) and max(scores) < NO_ANSWER_THRESHOLD
    if scores and not low_confidence:
        ordered = sorted(zip(candidates, scores), key=lambda pair: -pair[1])
    else:
        ordered = [(hits[cid], score) for cid, score in fused]

    log_candidates = [{"chunk_id": cid, "keyword_rank": keyword_rank.get(cid), "vector_rank": vector_rank.get(cid),
                       "rrf": round(score, 5), "rerank": round(dict(zip([c.chunk_id for c in candidates], scores)).get(cid, 0.0), 4) if scores else None}
                      for cid, score in fused]

    if not ordered:  # neither search found anything
        return RetrievalResult([], True, _log(workspace_id, session_id, query, scope, log_candidates, [], timings),
                               keyword_only)

    chosen = _diverse(ordered, keep)
    parents = store.parents_of([h.chunk_id for h, _ in chosen])
    sources: list[Hit] = []
    seen: set[int] = set()
    used = 0
    for hit, score in chosen:
        parent = parents.get(hit.chunk_id)
        if parent is None or parent.chunk_id in seen:
            continue
        tokens = count_tokens(parent.text)
        if sources and used + tokens > budget_tokens:
            continue
        seen.add(parent.chunk_id)
        used += tokens
        sources.append(Hit(parent.chunk_id, parent.document_id, parent.document_name, parent.text, parent.heading_path,
                           parent.page_start, parent.page_end, None, score))
    lap("expand")
    log_id = _log(workspace_id, session_id, query, scope, log_candidates, [s.chunk_id for s in sources], timings)
    return RetrievalResult(sources, False, log_id, keyword_only, low_confidence)

"""Retrieval quality on a golden set: ``python -m app.rag.eval [--real] [--update-baseline]``.

Indexes ``tests/rag_golden/corpus`` into a throwaway database, asks every question in
``questions.jsonl`` in four modes and reports, per mode:
  hit@8     the expected document is among the top 8 passages
  recall@8  a top-8 passage contains the expected answer phrase
  mrr       1 / rank of the first passage containing it (0 if none)
For hybrid+rerank it also reports how often unanswerable questions correctly get "not covered"
(no_answer) and how often answerable ones get it too (false_no_answer). "Not covered" here means
the result was empty or flagged low-confidence, which tells the answering model to check relevance.

Exit code 1 when hybrid+rerank recall@8 falls more than 0.05 below the recorded baseline for the
models in use (fake models in CI, real ones locally with --real).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

GOLDEN = Path(__file__).resolve().parents[2] / "tests" / "rag_golden"
BASELINE = GOLDEN / "baseline.json"
MODES = ("keyword", "vector", "hybrid", "hybrid+rerank")
K = 8
TOLERANCE = 0.05


@contextmanager
def _golden_database() -> Iterator[int]:
    """A temporary database holding the golden corpus; yields the library id."""
    previous = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(Path(tempfile.mkdtemp(prefix="nexus-rag-eval-")) / "eval.db")
    try:
        from app.core.database import init_db
        from app.rag import ingest, store

        init_db()
        conn = store.connect()
        store.ensure_vector_table(conn)
        conn.close()
        library = store.create_collection(1, "golden")
        for path in sorted((GOLDEN / "corpus").iterdir()):
            ingest.submit(1, library["id"], path.name, path.read_bytes())
        while (job := ingest._claim()) is not None:  # process synchronously, no background worker
            ingest._run_one(job)
        failed = [d["name"] for d in store.list_documents(library["id"]) if d["status"] != "ready"]
        if failed:
            raise RuntimeError(f"golden documents failed to index: {failed}")
        yield library["id"]
    finally:
        if previous is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous


def _questions() -> list[dict]:
    return [json.loads(line) for line in (GOLDEN / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _ranked(mode: str, question: str, library_id: int):
    """(passages as (document name, text), insufficient) for one question in one mode."""
    from app.rag import store
    from app.rag.embeddings import embed_cached
    from app.rag.retrieve import retrieve, rrf

    if mode == "hybrid+rerank":
        result = retrieve(question, collection_ids=[library_id])
        return [(s.document_name, s.text) for s in result.sources], result.insufficient or result.low_confidence
    keyword = store.keyword_search(1, [library_id], question, 40) if mode in ("keyword", "hybrid") else []
    vector = store.vector_search(1, [library_id], embed_cached([question])[0], 40) if mode in ("vector", "hybrid") else []
    hits = {h.chunk_id: h for h in keyword + vector}
    order = [cid for cid, _ in rrf([[h.chunk_id for h in keyword], [h.chunk_id for h in vector]])]
    parents = store.parents_of(order)
    passages, seen = [], set()
    for cid in order:
        parent = parents.get(cid, hits[cid])
        if parent.chunk_id not in seen:
            seen.add(parent.chunk_id)
            passages.append((parent.document_name, parent.text))
    return passages, False


def evaluate_all() -> dict[str, dict[str, float]]:
    questions = _questions()
    answerable = [q for q in questions if q["doc"]]
    unanswerable = [q for q in questions if not q["doc"]]
    results: dict[str, dict[str, float]] = {}
    with _golden_database() as library_id:
        for mode in MODES:
            hits = found = 0
            reciprocal = 0.0
            refused = 0
            for q in answerable:
                passages, insufficient = _ranked(mode, q["q"], library_id)
                top = passages[:K]
                refused += insufficient
                hits += any(name == q["doc"] for name, _ in top)
                rank = next((i for i, (_, text) in enumerate(top, start=1) if q["contains"].lower() in text.lower()), 0)
                found += rank > 0
                reciprocal += 1 / rank if rank else 0.0
            n = len(answerable)
            results[mode] = {"hit@8": round(hits / n, 3), "recall@8": round(found / n, 3), "mrr": round(reciprocal / n, 3)}
            if mode == "hybrid+rerank":
                correct = sum(_ranked(mode, q["q"], library_id)[1] for q in unanswerable)
                results[mode]["no_answer"] = round(correct / max(1, len(unanswerable)), 3)
                results[mode]["false_no_answer"] = round(refused / n, 3)
    return results


def _models_key() -> str:
    return "fake" if os.getenv("NEXUS_RAG_EMBEDDER") == "fake" else "real"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real", action="store_true", help="use the real local models (downloads them once)")
    parser.add_argument("--update-baseline", action="store_true", help="record these numbers as the new baseline")
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args(argv)
    if args.real:
        os.environ.pop("NEXUS_RAG_EMBEDDER", None)
        os.environ.pop("NEXUS_RAG_RERANKER", None)
        os.environ.setdefault("NEXUS_MODELS_DIR", str(Path(__file__).resolve().parents[2] / "data" / "models"))
    elif not os.getenv("NEXUS_RAG_EMBEDDER"):
        os.environ["NEXUS_RAG_EMBEDDER"] = os.environ["NEXUS_RAG_RERANKER"] = "fake"

    results = evaluate_all()
    key = _models_key()
    print(f"Retrieval quality on {len(_questions())} golden questions ({key} models)")
    print(f"{'mode':<16}{'hit@8':>8}{'recall@8':>10}{'mrr':>8}{'no_answer':>11}{'false_no':>10}")
    for mode, m in results.items():
        print(f"{mode:<16}{m['hit@8']:>8.3f}{m['recall@8']:>10.3f}{m['mrr']:>8.3f}"
              f"{m.get('no_answer', float('nan')):>11.3f}{m.get('false_no_answer', float('nan')):>10.3f}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    if args.update_baseline:
        baseline[key] = results
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline for {key} models updated.")
        return 0
    expected = baseline.get(key, {}).get("hybrid+rerank", {}).get("recall@8")
    actual = results["hybrid+rerank"]["recall@8"]
    if expected is not None and actual < expected - TOLERANCE:
        print(f"FAIL: hybrid+rerank recall@8 {actual:.3f} is below the baseline {expected:.3f} - {TOLERANCE}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

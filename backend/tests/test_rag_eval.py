"""RAG Task 11: the golden-set evaluation and its CI gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.rag import eval as rag_eval

BACKEND = Path(__file__).resolve().parents[1]


def test_eval_metrics_are_sane():
    results = rag_eval.evaluate_all()
    for mode in rag_eval.MODES:
        for metric in ("hit@8", "recall@8", "mrr"):
            assert 0 <= results[mode][metric] <= 1, (mode, metric)
    # With the word-matching fake models keyword search is naturally strongest; the meaningful
    # comparison (hybrid+rerank vs keyword-only) is the --real run recorded in baseline.json.
    assert results["hybrid"]["recall@8"] >= results["vector"]["recall@8"]
    assert 0 <= results["hybrid+rerank"]["no_answer"] <= 1


def test_cli_passes_against_the_committed_baseline():
    run = subprocess.run([sys.executable, "-m", "app.rag.eval"], cwd=BACKEND, capture_output=True, text=True,
                         env={**__import__("os").environ, "NEXUS_RAG_EMBEDDER": "fake", "NEXUS_RAG_RERANKER": "fake"})
    assert run.returncode == 0, run.stdout + run.stderr
    assert "hybrid+rerank" in run.stdout and "recall@8" in run.stdout

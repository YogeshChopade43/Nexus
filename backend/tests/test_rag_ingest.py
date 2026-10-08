"""RAG Task 6: background ingestion with retries, recovery and races."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.rag import embeddings, ingest, store
from app.rag.loaders import UnsupportedFile

DOC = b"# Policy\n\nRefunds are accepted within 30 days.\n\nShipping to Pune takes 5 business days."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def wait_for(document_id: int, statuses=("ready", "failed"), timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = store.get_document(document_id)
        if doc is None or doc["status"] in statuses:
            return doc
        time.sleep(0.05)
    raise AssertionError(f"document {document_id} stuck: {store.get_document(document_id)}")


def make_due(document_id: int) -> None:
    """Skip the retry backoff."""
    conn = get_connection()
    conn.execute("UPDATE ingestion_jobs SET next_attempt_at = '2000-01-01T00:00:00Z' WHERE document_id = ?", (document_id,))
    conn.commit()
    conn.close()
    ingest.worker.wake()


def job(document_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE document_id = ?", (document_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def test_upload_becomes_ready_and_searchable(client):
    lib = store.create_collection(1, "ingest ready")
    doc = ingest.submit(1, lib["id"], "policy.md", DOC)
    assert doc["status"] == "queued"
    doc = wait_for(doc["id"])
    assert doc["status"] == "ready" and doc["chunk_count"] > 0 and doc["progress"] == 100
    assert doc["embed_model"] == "fake-hash-384" and doc["chars"] > 0
    assert store.get_file(doc["id"]) is None  # the upload isn't kept once indexed
    assert store.keyword_search(1, [lib["id"]], "Pune")


def test_failure_retries_then_fails_and_can_be_retried(client, monkeypatch):
    lib = store.create_collection(1, "ingest retry")

    def boom(texts):
        raise RuntimeError("embedding exploded")

    monkeypatch.setattr(ingest, "embed_cached", boom)
    doc = ingest.submit(1, lib["id"], "retry.md", DOC + b" retry")
    for _ in range(ingest.MAX_ATTEMPTS):
        deadline = time.time() + 10
        while time.time() < deadline and job(doc["id"]).get("status") not in ("retry", "failed"):
            time.sleep(0.05)
        if job(doc["id"])["status"] == "failed":
            break
        make_due(doc["id"])
        time.sleep(0.1)
    doc = wait_for(doc["id"], ("failed",))
    assert doc["status"] == "failed" and "embedding exploded" in doc["error"]
    assert job(doc["id"])["attempts"] == ingest.MAX_ATTEMPTS == 4  # first try + 3 retries
    conn = get_connection()
    notified = conn.execute("SELECT COUNT(*) FROM activity_log WHERE type = 'document_failed' AND title LIKE '%retry.md%'").fetchone()[0]
    conn.close()
    assert notified == 1

    monkeypatch.undo()
    # The woken worker may already be processing (or done with) this small file by the time it returns.
    assert ingest.retry_document(doc["id"])["status"] in ("queued", "processing", "ready")
    assert wait_for(doc["id"])["status"] == "ready"


def test_unreadable_file_fails_without_retrying(client):
    from tests.helpers import make_pdf

    lib = store.create_collection(1, "ingest scanned")
    doc = ingest.submit(1, lib["id"], "scan.pdf", make_pdf([""]))
    doc = wait_for(doc["id"])
    assert doc["status"] == "failed" and "no selectable text" in doc["error"]
    assert job(doc["id"])["attempts"] == 1


def test_running_jobs_resume_after_restart(client):
    lib = store.create_collection(1, "ingest restart")
    doc = ingest.submit(1, lib["id"], "restart.md", DOC + b" restart")
    wait_for(doc["id"])
    # Simulate a crash mid-job: the row says running, the document says processing.
    conn = get_connection()
    conn.execute("UPDATE ingestion_jobs SET status = 'running' WHERE document_id = ?", (doc["id"],))
    conn.execute("UPDATE documents SET status = 'processing' WHERE id = ?", (doc["id"],))
    conn.execute("INSERT OR REPLACE INTO document_files (document_id, data) VALUES (?, ?)", (doc["id"], DOC + b" restart"))
    conn.commit()
    conn.close()
    ingest.recover_interrupted_jobs()
    ingest.worker.wake()
    assert wait_for(doc["id"])["status"] == "ready"


def test_concurrent_duplicate_upload(client):
    lib = store.create_collection(1, "ingest race")
    results, errors = [], []

    def upload():
        try:
            results.append(ingest.submit(1, lib["id"], "same.md", DOC + b" race"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=upload) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len({r["id"] for r in results}) == 1
    conn = get_connection()
    jobs = conn.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE document_id = ?", (results[0]["id"],)).fetchone()[0]
    conn.close()
    assert jobs == 1


def test_delete_during_processing(client, monkeypatch):
    lib = store.create_collection(1, "ingest delete")
    holder = {}
    real = ingest.embed_cached

    def delete_then_embed(texts):
        store.delete_document(holder["id"])
        return real(texts)

    monkeypatch.setattr(ingest, "embed_cached", delete_then_embed)
    doc = ingest.submit(1, lib["id"], "vanish.md", DOC + b" vanish")
    holder["id"] = doc["id"]
    deadline = time.time() + 10
    while time.time() < deadline and store.get_document(doc["id"]) is not None:
        time.sleep(0.05)
    time.sleep(0.3)  # let the job finish
    assert store.get_document(doc["id"]) is None
    conn = get_connection()
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc["id"],)).fetchone()[0] == 0
    conn.close()


def test_waits_for_model(client, monkeypatch):
    lib = store.create_collection(1, "ingest wait")
    monkeypatch.setattr(embeddings, "prepare_models", lambda: False)
    doc = ingest.submit(1, lib["id"], "wait.md", DOC + b" wait")
    time.sleep(0.5)
    doc = store.get_document(doc["id"])
    assert doc["status"] == "queued" and doc["error"] == "waiting for search model"
    assert job(doc["id"])["attempts"] == 0
    monkeypatch.undo()
    make_due(doc["id"])
    assert wait_for(doc["id"])["status"] == "ready"


def test_limits(client, monkeypatch):
    lib = store.create_collection(1, "ingest limits")
    with pytest.raises(ValueError, match="25 MB"):
        ingest.submit(1, lib["id"], "big.txt", b"a" * (25 * 1024 * 1024 + 1))
    with pytest.raises(UnsupportedFile):
        ingest.submit(1, lib["id"], "a.zip", b"PK\x03\x04zip")
    monkeypatch.setattr(ingest, "MAX_DOCUMENT_CHARS", 50)
    doc = wait_for(ingest.submit(1, lib["id"], "long.md", DOC + b" long")["id"])
    assert doc["status"] == "failed" and "50" in doc["error"]

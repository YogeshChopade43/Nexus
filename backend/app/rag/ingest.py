"""Ingestion: upload → queued job → load → chunk → embed → index, run by a background worker.

Jobs live in the database, so they survive restarts. Each document is indexed in one transaction:
its chunks, keyword rows and vectors appear together or not at all.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.database import get_connection, log_activity
from app.rag import embeddings, store
from app.rag.chunking import chunk, context_header
from app.rag.embeddings import BATCH, embed_cached
from app.rag.loaders import UnsupportedFile, detect_kind, load

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DOCUMENT_CHARS = 5_000_000
MAX_ATTEMPTS = 4  # the first try plus 3 retries
RETRY_DELAYS = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10))
MODEL_WAIT = timedelta(seconds=60)
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "html": "text/html",
        "markdown": "text/markdown", "csv": "text/csv", "text": "text/plain"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


class _Gone(Exception):
    """The document was deleted while it was being processed."""


def submit(workspace_id: int, collection_id: int, name: str, data: bytes) -> dict:
    """Validate and store an upload, and queue it unless the same file is already there."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{name} is larger than 25 MB")
    from app.quota import check_storage

    check_storage(len(data))
    kind = detect_kind(name, data)  # raises UnsupportedFile for files we can't read
    document, created = store.create_document(workspace_id, collection_id, name, MIME[kind], data)
    if created:
        _enqueue(workspace_id, document["id"])
        worker.wake()
    return document


def _enqueue(workspace_id: int, document_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ingestion_jobs (workspace_id, document_id, status, next_attempt_at, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?)", (workspace_id, document_id, _iso(_now()), _iso(_now()), _iso(_now())))
        conn.commit()
    finally:
        conn.close()


def retry_document(document_id: int) -> dict:
    document = store.get_document(document_id)
    if document is None:
        raise KeyError(document_id)
    if document["status"] != "failed" or store.get_file(document_id) is None:
        raise ValueError("Only failed documents can be retried")
    store.set_status(document_id, "queued", progress=0)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ingestion_jobs WHERE document_id = ?", (document_id,))
        conn.commit()
    finally:
        conn.close()
    _enqueue(document["workspace_id"], document_id)
    worker.wake()
    return store.get_document(document_id)


def recover_interrupted_jobs() -> int:
    """Jobs left running by a crash or restart go back in the queue."""
    conn = get_connection()
    try:
        count = conn.execute("UPDATE ingestion_jobs SET status = 'retry', next_attempt_at = ?, updated_at = ? "
                             "WHERE status = 'running'", (_iso(_now()), _iso(_now()))).rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def _claim() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "UPDATE ingestion_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? "
            "WHERE id = (SELECT id FROM ingestion_jobs WHERE status IN ('queued', 'retry') AND next_attempt_at <= ? "
            "ORDER BY id LIMIT 1) RETURNING *", (_iso(_now()), _iso(_now()))).fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def _update_job(job_id: int, **fields) -> None:
    conn = get_connection()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE ingestion_jobs SET {sets}, updated_at = ? WHERE id = ?",
                     (*fields.values(), _iso(_now()), job_id))
        conn.commit()
    finally:
        conn.close()


def _alive(document_id: int) -> dict:
    document = store.get_document(document_id)
    if document is None:
        raise _Gone()
    return document


def process_job(job: dict) -> None:
    """Index one document. Raises on failure; the worker decides whether to retry."""
    document_id = job["document_id"]
    document = _alive(document_id)
    store.set_status(document_id, "processing", progress=0)
    data = store.get_file(document_id)
    if data is None:
        raise UnsupportedFile("The uploaded file is no longer stored; please upload it again")
    loaded = load(document["name"], data)
    chars = sum(len(block.text) for block in loaded.blocks)
    if chars > MAX_DOCUMENT_CHARS:
        raise UnsupportedFile(f"{document['name']} has more than {MAX_DOCUMENT_CHARS:,} characters of text")
    parents, children = chunk(loaded)
    texts = [context_header(document["name"], c.heading_path) + c.text for c in children]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        vectors.extend(embed_cached(texts[start:start + BATCH]))
        _alive(document_id)
        progress = min(99, int(100 * len(vectors) / max(1, len(texts))))
        store.set_status(document_id, "processing", progress=progress)
        _update_job(job["id"], progress=progress)

    conn = store.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
            conn.rollback()
            raise _Gone()
        store.replace_chunks(conn, document_id, parents, children, vectors, document["name"])
        note = document["error"] if document["error"] == "re-upload recommended" else None
        store.set_status(document_id, "ready", error=note, progress=100, conn=conn, pages=loaded.pages, chars=chars,
                         chunk_count=len(children), embed_model=embeddings.get_embedder().model_id)
        conn.execute("DELETE FROM document_files WHERE document_id = ?", (document_id,))
        conn.execute("UPDATE ingestion_jobs SET status = 'done', progress = 100 WHERE id = ?", (job["id"],))
        conn.commit()
    finally:
        conn.close()
    log_activity("settings_changed", f"Document '{document['name']}' ready", f"{len(children)} passage(s)",
                 {"document_id": document_id})


def _run_one(job: dict) -> None:
    """Process a claimed job as the document's owner (their bell hears how it went)."""
    from app.auth.owner import as_user
    from app.core.database import get_connection

    conn = get_connection()
    try:
        row = conn.execute("SELECT user_id FROM workspaces WHERE id = ?", (job.get("workspace_id"),)).fetchone()
    finally:
        conn.close()
    if row is None or row["user_id"] is None:
        _run_one_as_owner(job)
        return
    with as_user(int(row["user_id"])):
        _run_one_as_owner(job)


def _run_one_as_owner(job: dict) -> None:
    """Process a claimed job and record the outcome (retry, failure, or nothing to do)."""
    document_id = job["document_id"]
    if not embeddings.prepare_models():
        # Not the document's fault: wait without using up an attempt.
        store.set_status(document_id, "queued", error="waiting for search model")
        _update_job(job["id"], status="queued", attempts=job["attempts"] - 1,
                    next_attempt_at=_iso(_now() + MODEL_WAIT))
        return
    try:
        process_job(job)
    except _Gone:
        return
    except Exception as exc:  # noqa: BLE001 - every failure is reported on the document
        message = str(exc) or exc.__class__.__name__
        permanent = isinstance(exc, UnsupportedFile)
        if permanent or job["attempts"] >= MAX_ATTEMPTS:
            _update_job(job["id"], status="failed", last_error=message)
            if store.get_document(document_id) is not None:
                store.set_status(document_id, "failed", error=message)
                name = store.get_document(document_id)["name"]
                log_activity("document_failed", f"Document '{name}' could not be added", message,
                             {"document_id": document_id})
        else:
            logger.warning("Ingestion of document %s failed (attempt %s): %s", document_id, job["attempts"], message)
            _update_job(job["id"], status="retry", last_error=message,
                        next_attempt_at=_iso(_now() + RETRY_DELAYS[job["attempts"] - 1]))
            if store.get_document(document_id) is not None:
                store.set_status(document_id, "queued", error=f"retrying: {message}")


class Worker:
    """Processes due jobs one at a time in a thread, so the web server stays responsive."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._event: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        recover_interrupted_jobs()
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="rag-ingestion")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def wake(self) -> None:
        if self._loop and self._event and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._event.set)

    async def _run(self) -> None:
        while True:
            job = await asyncio.to_thread(_claim)
            if job is None:
                self._event.clear()
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await asyncio.to_thread(_run_one, job)
            except Exception:  # never let one bad job stop the worker
                logger.exception("Ingestion worker error on job %s", job["id"])


worker = Worker()

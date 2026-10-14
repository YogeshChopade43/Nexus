"""RAG Task 1: migration 6 creates the workspace-owned RAG tables and keeps the old ones as legacy."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.database import MIGRATIONS, get_connection
from app.main import app

RAG_TABLES = {
    "workspaces", "collections", "documents", "document_files", "chunks", "chunk_fts", "ingestion_jobs",
    "retrieval_logs", "embedding_cache",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.sqlite_only
def test_migration_creates_rag_tables_and_retires_legacy(client):
    conn = get_connection()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert RAG_TABLES <= tables, RAG_TABLES - tables
        # Migration 6 keeps the old tables as legacy_*; the startup import drops them once emptied.
        assert not {"legacy_documents", "legacy_document_chunks"} & tables
        assert "answer_feedback" not in tables  # the feedback feature was removed (migration 8)
        assert conn.execute("SELECT name FROM workspaces WHERE id = 1").fetchone()[0] == "Default"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)

        collection = conn.execute(
            "INSERT INTO collections (workspace_id, name, kind, created_at) VALUES (1, 'schema-test', 'library', 'now')"
        ).lastrowid
        insert = ("INSERT INTO documents (workspace_id, collection_id, name, mime, size_bytes, content_hash, version, "
                  "status, created_at, updated_at) VALUES (1, ?, 'a.txt', 'text/plain', 1, 'h1', 1, 'queued', 'now', 'now')")
        conn.execute(insert, (collection,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (collection,))  # same file twice in one collection
    finally:
        conn.rollback()
        conn.close()

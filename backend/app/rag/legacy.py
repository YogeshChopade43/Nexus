"""One-time import of documents from the old keyword-only knowledge base (migration 5 tables).

Their original files weren't kept, so each document's text is rebuilt by joining its old chunks
and removing the overlaps, then sent through the normal ingestion pipeline into a library named
"Imported". The legacy tables are dropped once they are empty.
"""
from __future__ import annotations

import logging

from app.core.database import get_connection, is_postgres
from app.rag import ingest, store
from app.rag.models import DEFAULT_WORKSPACE

logger = logging.getLogger(__name__)

LIBRARY = "Imported"
REUPLOAD = "re-upload recommended"
MAX_OVERLAP = 400
LEGACY_OVERLAP = 200  # the old chunker's overlap


def _join(chunks: list[str]) -> tuple[str, bool]:
    """Concatenate overlapping chunks; False if an overlap couldn't be found (text may be off)."""
    text, exact = chunks[0] if chunks else "", True
    for chunk in chunks[1:]:
        tail = text[-MAX_OVERLAP:]
        # The old chunker overlapped by 200 characters (less any whitespace it stripped); check lengths
        # nearest 200 first so repetitive text doesn't match a wrong, longer overlap.
        limit = min(len(tail), len(chunk))
        candidates = sorted(range(1, limit + 1), key=lambda k: abs(k - LEGACY_OVERLAP))
        overlap = next((k for k in candidates if tail.endswith(chunk[:k])), 0)
        if overlap == 0:
            exact = False
            text += "\n" + chunk
        else:
            text += chunk[overlap:]
    return text, exact


def _legacy_tables(conn) -> bool:
    if is_postgres():
        return False  # PostgreSQL installs start after the old knowledge base
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name IN ('legacy_documents', 'legacy_document_chunks')")}
    return names == {"legacy_documents", "legacy_document_chunks"}


def import_legacy_documents() -> int:
    """Import every legacy document, delete it from the legacy tables, and drop them when empty."""
    conn = get_connection()
    try:
        if not _legacy_tables(conn):
            return 0
        documents = [dict(r) for r in conn.execute("SELECT id, name FROM legacy_documents ORDER BY id")]
    finally:
        conn.close()

    imported = 0
    library = None
    for doc in documents:
        conn = get_connection()
        try:
            chunks = [r[0] for r in conn.execute(
                "SELECT content FROM legacy_document_chunks WHERE doc_id = ? ORDER BY CAST(position AS INTEGER)",
                (doc["id"],))]
        finally:
            conn.close()
        text, exact = _join(chunks)
        if text.strip():
            library = library or next((c for c in store.list_collections(DEFAULT_WORKSPACE) if c["name"] == LIBRARY), None) \
                or store.create_collection(DEFAULT_WORKSPACE, LIBRARY)
            try:
                new = ingest.submit(DEFAULT_WORKSPACE, library["id"], doc["name"], text.encode("utf-8"))
                if not exact:
                    store.set_status(new["id"], new["status"], error=REUPLOAD)
                imported += 1
            except ValueError as exc:  # includes UnsupportedFile
                logger.warning("Could not import legacy document %s: %s", doc["name"], exc)
        conn = get_connection()
        try:
            conn.execute("DELETE FROM legacy_document_chunks WHERE doc_id = ?", (doc["id"],))
            conn.execute("DELETE FROM legacy_documents WHERE id = ?", (doc["id"],))
            conn.commit()
        finally:
            conn.close()

    conn = get_connection()
    try:
        if _legacy_tables(conn) and conn.execute("SELECT COUNT(*) FROM legacy_documents").fetchone()[0] == 0:
            conn.executescript("DROP TABLE legacy_document_chunks; DROP TABLE legacy_documents;")
    finally:
        conn.close()
    if imported:
        logger.info("Imported %d document(s) from the old knowledge base into '%s'", imported, LIBRARY)
    return imported

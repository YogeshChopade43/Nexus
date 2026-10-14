"""SQLite storage for RAG: collections, documents, chunks, the FTS5 keyword index and the vector index.

Vectors live in a ``sqlite-vec`` table partitioned by workspace with the collection as a filterable
column. If the extension can't load on this platform, a plain table plus a Python cosine scan is
used instead (fine below ~50k chunks).
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from array import array
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Optional

from app.core.database import get_connection, is_postgres
from app.rag.chunking import context_header
from app.rag.embeddings import DIM
from app.rag.models import ChunkDraft, Hit

logger = logging.getLogger(__name__)

MAX_DOCUMENTS_PER_COLLECTION = 500
_backend: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---- connections and the vector table ---------------------------------------------------

def _load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:  # missing wheel, or Python built without extension loading
        logger.debug("sqlite-vec unavailable: %s", exc)
        return False


def vector_backend() -> Literal["sqlite-vec", "python"]:
    global _backend
    if is_postgres():
        return "python"  # ponytail: Python cosine scan on PostgreSQL; pgvector when collections get large
    if _backend is None:
        probe = sqlite3.connect(":memory:")
        _backend = "sqlite-vec" if _load_vec(probe) else "python"
        probe.close()
        if _backend == "python":
            logger.warning("sqlite-vec could not be loaded; vector search falls back to a slower Python scan")
    return _backend  # type: ignore[return-value]


def connect() -> sqlite3.Connection:
    conn = get_connection()
    if vector_backend() == "sqlite-vec":
        _load_vec(conn)
    return conn


def ensure_vector_table(conn: sqlite3.Connection) -> None:
    if is_postgres():
        return  # in schema_postgres.sql
    if vector_backend() == "sqlite-vec":
        conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
                     f"workspace_id integer partition key, collection_id integer, embedding float[{DIM}])")
    else:
        conn.execute("CREATE TABLE IF NOT EXISTS chunk_vectors (chunk_id INTEGER PRIMARY KEY, workspace_id INTEGER, "
                     "collection_id INTEGER, vector BLOB NOT NULL)")
    conn.commit()


def _vector_tables(conn: sqlite3.Connection) -> set[str]:
    if is_postgres():
        return {"chunk_vectors"}
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name IN ('chunk_vec', 'chunk_vectors')")}


def _blob(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


# ---- collections --------------------------------------------------------------------------

def user_workspace() -> int:
    """The signed-in person's workspace (their libraries, chat files and passages), made on first use."""
    from app.auth.owner import owner_id

    owner = owner_id()
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM workspaces WHERE user_id = ? ORDER BY id LIMIT 1", (owner,)).fetchone()
        if row:
            return int(row[0])
        cursor = conn.execute("INSERT INTO workspaces (name, user_id) VALUES (?, ?)", ("Personal", owner))
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def create_collection(workspace_id: int, name: str, kind: str = "library", session_id: Optional[str] = None) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("A library needs a name")
    conn = get_connection()
    try:
        try:
            cursor = conn.execute(
                "INSERT INTO collections (workspace_id, name, kind, session_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (workspace_id, name, kind, session_id, _now()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f'A library named "{name}" already exists') from None
        conn.commit()
        return dict(conn.execute("SELECT * FROM collections WHERE id = ?", (cursor.lastrowid,)).fetchone())
    finally:
        conn.close()


def get_collection(collection_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def chat_collection(workspace_id: int, session_id: str) -> dict:
    """The collection holding one conversation's attachments (created on first use)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM collections WHERE kind = 'chat' AND session_id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    if row:
        return dict(row)
    try:
        return create_collection(workspace_id, f"chat:{session_id}", "chat", session_id)
    except ValueError:  # created concurrently
        return chat_collection(workspace_id, session_id)


def list_collections(workspace_id: int) -> list[dict]:
    """Libraries (not chat collections) with document counts by status."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT c.*, COUNT(d.id) AS documents, "
            "SUM(CASE WHEN d.status = 'ready' THEN 1 ELSE 0 END) AS ready "
            "FROM collections c LEFT JOIN documents d ON d.collection_id = c.id "
            "WHERE c.workspace_id = ? AND c.kind = 'library' GROUP BY c.id ORDER BY lower(c.name)",
            (workspace_id,),
        ).fetchall()
        return [{**dict(r), "ready": r["ready"] or 0} for r in rows]
    finally:
        conn.close()


def rename_collection(collection_id: int, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("A library needs a name")
    conn = get_connection()
    try:
        try:
            conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
        except sqlite3.IntegrityError:
            raise ValueError(f'A library named "{name}" already exists') from None
        conn.commit()
    finally:
        conn.close()
    return get_collection(collection_id)


def delete_collection(collection_id: int) -> bool:
    conn = get_connection()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE collection_id = ?", (collection_id,))]
    finally:
        conn.close()
    for document_id in ids:
        delete_document(document_id)
    conn = get_connection()
    try:
        deleted = conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,)).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


# ---- documents ----------------------------------------------------------------------------

def create_document(workspace_id: int, collection_id: int, name: str, mime: str, data: bytes) -> tuple[dict, bool]:
    """Store an upload as ``queued``. Returns (document, created); the same bytes in the same
    collection return the existing document. The same name with new bytes is a new version."""
    content_hash = hashlib.sha256(data).hexdigest()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM documents WHERE collection_id = ? AND content_hash = ?",
                                (collection_id, content_hash)).fetchone()
        if existing:
            return dict(existing), False
        count = conn.execute("SELECT COUNT(*) FROM documents WHERE collection_id = ?", (collection_id,)).fetchone()[0]
        if count >= MAX_DOCUMENTS_PER_COLLECTION:
            raise ValueError(f"A library can hold {MAX_DOCUMENTS_PER_COLLECTION} documents; this one is full")
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM documents WHERE collection_id = ? AND name = ?",
                               (collection_id, name)).fetchone()[0]
        try:
            cursor = conn.execute(
                "INSERT INTO documents (workspace_id, collection_id, name, mime, size_bytes, content_hash, version, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (workspace_id, collection_id, name, mime, len(data), content_hash, version, _now(), _now()),
            )
        except sqlite3.IntegrityError:  # the same file uploaded at the same moment
            conn.rollback()
            row = conn.execute("SELECT * FROM documents WHERE collection_id = ? AND content_hash = ?",
                               (collection_id, content_hash)).fetchone()
            return dict(row), False
        conn.execute("INSERT INTO document_files (document_id, data) VALUES (?, ?)", (cursor.lastrowid, data))
        conn.commit()
        return dict(conn.execute("SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)).fetchone()), True
    finally:
        conn.close()


def get_document(document_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_file(document_id: int) -> Optional[bytes]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT data FROM document_files WHERE document_id = ?", (document_id,)).fetchone()
        return bytes(row[0]) if row else None
    finally:
        conn.close()


def list_documents(collection_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE collection_id = ? ORDER BY id DESC", (collection_id,)).fetchall()]
    finally:
        conn.close()


def set_status(document_id: int, status: str, error: Optional[str] = None, progress: Optional[int] = None,
               conn: Optional[sqlite3.Connection] = None, **fields: Any) -> None:
    own = conn is None
    conn = conn or get_connection()
    try:
        sets = ["status = ?", "error = ?", "updated_at = ?"]
        values: list[Any] = [status, error, _now()]
        if progress is not None:
            sets.append("progress = ?")
            values.append(progress)
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            values.append(value)
        conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", (*values, document_id))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _delete_chunks(conn: sqlite3.Connection, chunk_ids: list[int]) -> None:
    tables = _vector_tables(conn)
    for start in range(0, len(chunk_ids), 500):
        batch = chunk_ids[start:start + 500]
        marks = ",".join("?" * len(batch))
        conn.execute(f"DELETE FROM chunk_fts WHERE rowid IN ({marks})", batch)
        if "chunk_vec" in tables:
            conn.execute(f"DELETE FROM chunk_vec WHERE rowid IN ({marks})", batch)
        if "chunk_vectors" in tables:
            conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN ({marks})", batch)
        conn.execute(f"DELETE FROM chunks WHERE id IN ({marks})", batch)


def delete_document(document_id: int) -> bool:
    conn = connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,))]
        _delete_chunks(conn, ids)
        conn.execute("DELETE FROM document_files WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM ingestion_jobs WHERE document_id = ?", (document_id,))
        deleted = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,)).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


def move_document(document_id: int, collection_id: int) -> dict:
    conn = connect()
    try:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            raise KeyError(document_id)
        try:
            conn.execute("UPDATE documents SET collection_id = ?, updated_at = ? WHERE id = ?",
                         (collection_id, _now(), document_id))
        except sqlite3.IntegrityError:
            raise ValueError("That library already has this exact file") from None
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,))]
        tables = _vector_tables(conn)
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            marks = ",".join("?" * len(batch))
            if "chunk_vec" in tables:
                # sqlite-vec can't UPDATE rows of a partitioned table, so move them by re-inserting.
                rows = conn.execute(f"SELECT rowid, workspace_id, embedding FROM chunk_vec WHERE rowid IN ({marks})",
                                    batch).fetchall()
                conn.execute(f"DELETE FROM chunk_vec WHERE rowid IN ({marks})", batch)
                conn.executemany(
                    "INSERT INTO chunk_vec (rowid, workspace_id, collection_id, embedding) VALUES (?, ?, ?, ?)",
                    [(r[0], r[1], collection_id, r[2]) for r in rows])
            if "chunk_vectors" in tables:
                conn.execute(f"UPDATE chunk_vectors SET collection_id = ? WHERE chunk_id IN ({marks})", (collection_id, *batch))
        conn.commit()
    finally:
        conn.close()
    return get_document(document_id)


def replace_chunks(conn: sqlite3.Connection, document_id: int, parents: list[ChunkDraft], children: list[ChunkDraft],
                   vectors: list[list[float]], document_name: str) -> None:
    """Swap in a document's chunks (and drop older versions of the same file) inside the caller's
    transaction, so searches see the old version or the new one, never a mix."""
    doc = conn.execute("SELECT workspace_id, collection_id, name, version FROM documents WHERE id = ?",
                       (document_id,)).fetchone()
    workspace_id, collection_id = doc["workspace_id"], doc["collection_id"]
    old_versions = [r[0] for r in conn.execute(
        "SELECT id FROM documents WHERE collection_id = ? AND name = ? AND version < ? AND id != ?",
        (collection_id, doc["name"], doc["version"], document_id))]
    old_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM chunks WHERE document_id IN ({','.join('?' * (len(old_versions) + 1))})",
        (document_id, *old_versions))]
    _delete_chunks(conn, old_ids)
    for old in old_versions:
        conn.execute("DELETE FROM document_files WHERE document_id = ?", (old,))
        conn.execute("DELETE FROM ingestion_jobs WHERE document_id = ?", (old,))
        conn.execute("DELETE FROM documents WHERE id = ?", (old,))

    parent_ids: list[int] = []
    for position, parent in enumerate(parents):
        parent_ids.append(_insert_chunk(conn, document_id, workspace_id, None, position, parent))
    use_vec = vector_backend() == "sqlite-vec"
    for position, (child, vector) in enumerate(zip(children, vectors)):
        parent_id = parent_ids[child.parent_index] if child.parent_index is not None else None
        chunk_id = _insert_chunk(conn, document_id, workspace_id, parent_id, position, child)
        conn.execute("INSERT INTO chunk_fts (rowid, text, heading_path, document_name) VALUES (?, ?, ?, ?)",
                      (chunk_id, context_header(document_name, child.heading_path) + child.text, child.heading_path,
                       document_name))
        if use_vec:
            conn.execute("INSERT INTO chunk_vec (rowid, workspace_id, collection_id, embedding) VALUES (?, ?, ?, ?)",
                         (chunk_id, workspace_id, collection_id, _blob(vector)))
        else:
            conn.execute("INSERT INTO chunk_vectors (chunk_id, workspace_id, collection_id, vector) VALUES (?, ?, ?, ?)",
                         (chunk_id, workspace_id, collection_id, _blob(vector)))


def _insert_chunk(conn: sqlite3.Connection, document_id: int, workspace_id: int, parent_id: Optional[int],
                  position: int, draft: ChunkDraft) -> int:
    return conn.execute(
        "INSERT INTO chunks (document_id, workspace_id, parent_id, kind, position, text, heading_path, page_start, "
        "page_end, char_start, char_end, tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (document_id, workspace_id, parent_id, draft.kind, position, draft.text, draft.heading_path, draft.page_start,
         draft.page_end, draft.char_start, draft.char_end, draft.tokens),
    ).lastrowid


# ---- search -------------------------------------------------------------------------------

_HIT_COLUMNS = ("c.id, c.document_id, d.name AS document_name, c.text, c.heading_path, c.page_start, c.page_end, "
                "c.parent_id")


def _hit(row: Any, score: float) -> Hit:
    return Hit(row["id"], row["document_id"], row["document_name"], row["text"], row["heading_path"],
               row["page_start"], row["page_end"], row["parent_id"], score)


def _fts_query(query: str) -> str:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words[:30]))


def keyword_search(workspace_id: int, collection_ids: list[int], query: str, limit: int = 40) -> list[Hit]:
    match = _fts_query(query)
    if not match or not collection_ids:
        return []
    marks = ",".join("?" * len(collection_ids))
    conn = get_connection()
    try:
        if is_postgres():
            words = match.replace('"', "").replace(" OR ", " | ")  # the same words, as a tsquery
            rows = conn.execute(
                f"SELECT {_HIT_COLUMNS}, -ts_rank(chunk_fts.tsv, to_tsquery('english', ?)) AS rank FROM chunk_fts "
                f"JOIN chunks c ON c.id = chunk_fts.rowid JOIN documents d ON d.id = c.document_id "
                f"WHERE chunk_fts.tsv @@ to_tsquery('english', ?) AND d.workspace_id = ? AND d.collection_id IN ({marks}) "
                f"AND d.status = 'ready' ORDER BY rank LIMIT ?",
                (words, words, workspace_id, *collection_ids, limit),
            ).fetchall()
            return [_hit(r, -float(r["rank"])) for r in rows]
        rows = conn.execute(
            f"SELECT {_HIT_COLUMNS}, bm25(chunk_fts) AS rank FROM chunk_fts "
            f"JOIN chunks c ON c.id = chunk_fts.rowid JOIN documents d ON d.id = c.document_id "
            f"WHERE chunk_fts MATCH ? AND d.workspace_id = ? AND d.collection_id IN ({marks}) AND d.status = 'ready' "
            f"ORDER BY rank LIMIT ?",
            (match, workspace_id, *collection_ids, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_hit(r, -float(r["rank"])) for r in rows]


def vector_search(workspace_id: int, collection_ids: list[int], vector: list[float], limit: int = 40) -> list[Hit]:
    if not collection_ids:
        return []
    marks = ",".join("?" * len(collection_ids))
    conn = connect()
    try:
        tables = _vector_tables(conn)
        scored: list[tuple[int, float]] = []
        if vector_backend() == "sqlite-vec" and "chunk_vec" in tables:
            # Vectors are unit length, so cosine similarity = 1 - L2² / 2.
            scored = [(r[0], 1 - float(r[1]) ** 2 / 2) for r in conn.execute(
                f"SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? AND k = ? AND workspace_id = ? "
                f"AND collection_id IN ({marks})",
                (_blob(vector), limit, workspace_id, *collection_ids))]
        if "chunk_vectors" in tables:  # Python fallback (and anything indexed while it was active)
            for chunk_id, blob in conn.execute(
                    f"SELECT chunk_id, vector FROM chunk_vectors WHERE workspace_id = ? AND collection_id IN ({marks})",
                    (workspace_id, *collection_ids)):
                scored.append((chunk_id, sum(a * b for a, b in zip(vector, array("f", blob)))))
        scored = sorted(scored, key=lambda s: -s[1])[:limit]
        if not scored:
            return []
        rows = {r["id"]: r for r in conn.execute(
            f"SELECT {_HIT_COLUMNS} FROM chunks c JOIN documents d ON d.id = c.document_id "
            f"WHERE c.id IN ({','.join('?' * len(scored))}) AND d.status = 'ready'",
            [s[0] for s in scored])}
    finally:
        conn.close()
    return [_hit(rows[cid], score) for cid, score in scored if cid in rows]


def parents_of(chunk_ids: Iterable[int]) -> dict[int, Hit]:
    """child chunk id → its parent section (the child itself if it has none)."""
    ids = list(chunk_ids)
    if not ids:
        return {}
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT child.id AS child_id, {_HIT_COLUMNS.replace('c.', 'p.')} FROM chunks child "
            f"JOIN chunks p ON p.id = COALESCE(child.parent_id, child.id) JOIN documents d ON d.id = p.document_id "
            f"WHERE child.id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
    finally:
        conn.close()
    return {r["child_id"]: _hit(r, 0.0) for r in rows}


def get_chunk_with_neighbours(chunk_id: int) -> dict:
    """A chunk with the chunks just before and after it in the same document (for the Sources panel)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT c.*, d.name AS document_name FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ?",
            (chunk_id,)).fetchone()
        if row is None:
            raise KeyError(chunk_id)
        siblings = conn.execute(
            "SELECT id, text FROM chunks WHERE document_id = ? AND kind = ? AND position IN (?, ?) ORDER BY position",
            (row["document_id"], row["kind"], row["position"] - 1, row["position"] + 1)).fetchall()
    finally:
        conn.close()
    before = [dict(s) for s in siblings if s["id"] < row["id"]]
    after = [dict(s) for s in siblings if s["id"] > row["id"]]
    return {"chunk": dict(row), "before": before[0] if before else None, "after": after[0] if after else None}

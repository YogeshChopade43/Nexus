"""Documents and libraries for retrieval (see app/rag). Thin handlers: logic lives in app.rag."""
from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.rag.store import user_workspace
from app.core.database import get_connection
from app.rag import ingest, store
from app.rag.embeddings import models_ready
from app.rag.loaders import UnsupportedFile
from app.rag.retrieve import retrieve

router = APIRouter(prefix="/api/rag", tags=["rag"])


class CollectionIn(BaseModel):
    name: str = Field(max_length=100)


class SearchIn(BaseModel):
    query: str = Field(max_length=2000)
    collection_ids: Optional[list[int]] = None
    session_id: Optional[str] = None


class MoveIn(BaseModel):
    collection_id: int


def _collection_or_404(collection_id: int) -> dict:
    collection = store.get_collection(collection_id)
    if collection is None or collection["workspace_id"] != user_workspace():
        raise HTTPException(status_code=404, detail="Library not found")
    return collection


def _document_or_404(document_id: int) -> dict:
    document = store.get_document(document_id)
    if document is None or document["workspace_id"] != user_workspace():
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _name_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=409 if "already exists" in str(exc) else 422, detail=str(exc))


async def _files(request: Request) -> list[tuple[str, bytes]]:
    """Multipart field ``file`` (one or more), or JSON ``{name, content_base64}`` (chat attachments)."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        uploads = [f for f in form.getlist("file") if hasattr(f, "read")]
        for upload in uploads:  # refuse before reading: a huge file must not be loaded into memory
            if upload.size is not None and upload.size > ingest.MAX_FILE_BYTES:
                raise HTTPException(status_code=422, detail=f"{upload.filename} is larger than 25 MB")
        return [(u.filename or "upload", await u.read()) for u in uploads]
    body = await request.json()
    try:
        return [(str(body["name"]), base64.b64decode(body["content_base64"], validate=True))]
    except (KeyError, TypeError, binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Send files as multipart 'file' fields or JSON {name, content_base64}")


def _submit_all(collection_id: int, files: list[tuple[str, bytes]]) -> list[dict]:
    if not files:
        raise HTTPException(status_code=422, detail="No file was uploaded")
    documents = []
    for name, data in files:
        try:
            documents.append(ingest.submit(user_workspace(), collection_id, name, data))
        except (UnsupportedFile, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    return documents


# ---- libraries ------------------------------------------------------------------------

@router.get("/collections")
def collections() -> list[dict[str, Any]]:
    return store.list_collections(user_workspace())


@router.post("/collections")
def create_collection(body: CollectionIn) -> dict[str, Any]:
    try:
        return store.create_collection(user_workspace(), body.name)
    except ValueError as exc:
        raise _name_error(exc)


@router.patch("/collections/{collection_id}")
def rename_collection(collection_id: int, body: CollectionIn) -> dict[str, Any]:
    _collection_or_404(collection_id)
    try:
        return store.rename_collection(collection_id, body.name)
    except ValueError as exc:
        raise _name_error(exc)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int) -> Response:
    _collection_or_404(collection_id)
    store.delete_collection(collection_id)
    return Response(status_code=204)


@router.get("/collections/{collection_id}/documents")
def collection_documents(collection_id: int) -> list[dict[str, Any]]:
    _collection_or_404(collection_id)
    return store.list_documents(collection_id)


@router.post("/collections/{collection_id}/documents")
async def upload(collection_id: int, request: Request) -> list[dict[str, Any]]:
    _collection_or_404(collection_id)
    return _submit_all(collection_id, await _files(request))


@router.post("/chats/{session_id}/documents")
async def upload_to_chat(session_id: str, request: Request) -> list[dict[str, Any]]:
    """Files attached in a conversation: searchable only in that conversation."""
    collection = store.chat_collection(user_workspace(), session_id)
    return _submit_all(collection["id"], await _files(request))


# ---- documents --------------------------------------------------------------------------

@router.get("/documents/{document_id}")
def document(document_id: int) -> dict[str, Any]:
    return _document_or_404(document_id)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int) -> Response:
    _document_or_404(document_id)
    store.delete_document(document_id)
    return Response(status_code=204)


@router.post("/documents/{document_id}/retry")
def retry_document(document_id: int) -> dict[str, Any]:
    _document_or_404(document_id)
    try:
        return ingest.retry_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/documents/{document_id}/move")
def move_document(document_id: int, body: MoveIn) -> dict[str, Any]:
    _document_or_404(document_id)
    if _collection_or_404(body.collection_id)["kind"] != "library":
        raise HTTPException(status_code=422, detail="Documents can only be moved into a library")
    try:
        return store.move_document(document_id, body.collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/documents/{document_id}/chunks/{chunk_id}")
def chunk(document_id: int, chunk_id: int) -> dict[str, Any]:
    _document_or_404(document_id)
    try:
        view = store.get_chunk_with_neighbours(chunk_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Passage not found")
    if view["chunk"]["document_id"] != document_id:
        raise HTTPException(status_code=404, detail="Passage not found")
    return view


# ---- search, status --------------------------------------------------------------

@router.post("/search")
def search(body: SearchIn) -> dict[str, Any]:
    result = retrieve(body.query, session_id=body.session_id, collection_ids=body.collection_ids)
    return {"sources": [asdict(s) for s in result.sources], "insufficient": result.insufficient,
            "keyword_only": result.keyword_only, "log_id": result.log_id}


@router.get("/status")
def status() -> dict[str, Any]:
    conn = get_connection()
    try:
        jobs = dict(conn.execute("SELECT status, COUNT(*) FROM ingestion_jobs WHERE workspace_id = ? GROUP BY status",
                                 (user_workspace(),)).fetchall())
        docs = dict(conn.execute("SELECT status, COUNT(*) FROM documents WHERE workspace_id = ? GROUP BY status",
                                 (user_workspace(),)).fetchall())
    finally:
        conn.close()
    return {
        "models_ready": models_ready(),
        "vector_backend": store.vector_backend(),
        "queue": {s: jobs.get(s, 0) for s in ("queued", "running", "retry")},
        "documents": {s: docs.get(s, 0) for s in ("queued", "processing", "ready", "failed")},
    }

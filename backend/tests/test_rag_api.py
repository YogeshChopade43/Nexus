"""RAG Task 9: the HTTP API (libraries, uploads, documents, search, chunks, status)."""
from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

API = "/api/rag"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def wait_ready(client, collection_id: int, count: int, timeout: float = 10) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = client.get(f"{API}/collections/{collection_id}/documents").json()
        if len(docs) >= count and all(d["status"] in ("ready", "failed") for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError(client.get(f"{API}/collections/{collection_id}/documents").json())


def test_round_trip(client):
    lib = client.post(f"{API}/collections", json={"name": "Policies"}).json()
    assert client.post(f"{API}/collections", json={"name": "Policies"}).status_code == 409
    files = [("file", ("policy.md", b"# Policy\n\nShipping to Pune takes 5 business days.", "text/markdown")),
             ("file", ("faq.txt", b"Refunds are accepted within 30 days.", "text/plain"))]
    uploaded = client.post(f"{API}/collections/{lib['id']}/documents", files=files)
    assert uploaded.status_code == 200, uploaded.text
    assert {d["name"] for d in uploaded.json()} == {"policy.md", "faq.txt"}
    docs = wait_ready(client, lib["id"], 2)
    assert {d["status"] for d in docs} == {"ready"}
    listed = client.get(f"{API}/collections").json()
    assert any(c["id"] == lib["id"] and c["documents"] == 2 and c["ready"] == 2 for c in listed)

    found = client.post(f"{API}/search", json={"query": "shipping Pune", "collection_ids": [lib["id"]]}).json()
    assert found["sources"][0]["document_name"] == "policy.md" and found["log_id"]
    chunk = client.get(f"{API}/documents/{found['sources'][0]['document_id']}/chunks/{found['sources'][0]['chunk_id']}").json()
    assert "Pune" in chunk["chunk"]["text"] and "before" in chunk and "after" in chunk

    assert client.post(f"{API}/feedback", json={"log_id": found["log_id"], "rating": 1}).status_code == 404

    other = client.post(f"{API}/collections", json={"name": "Archive"}).json()
    moved = client.post(f"{API}/documents/{docs[0]['id']}/move", json={"collection_id": other["id"]}).json()
    assert moved["collection_id"] == other["id"]
    assert client.patch(f"{API}/collections/{other['id']}", json={"name": "Old stuff"}).json()["name"] == "Old stuff"

    assert client.delete(f"{API}/collections/{lib['id']}").status_code == 204
    assert client.get(f"{API}/documents/{docs[1]['id']}").status_code == 404
    status = client.get(f"{API}/status").json()
    assert status["models_ready"] is True and status["vector_backend"] in ("sqlite-vec", "python")
    assert set(status["documents"]) == {"queued", "processing", "ready", "failed"}


def test_json_upload_and_retry(client):
    from tests.helpers import make_pdf

    lib = client.post(f"{API}/collections", json={"name": "Scans"}).json()
    body = {"name": "scan.pdf", "content_base64": base64.b64encode(make_pdf([""])).decode()}
    doc = client.post(f"{API}/collections/{lib['id']}/documents", json=body).json()[0]
    failed = wait_ready(client, lib["id"], 1)[0]
    assert failed["status"] == "failed" and "no selectable text" in failed["error"]
    assert client.post(f"{API}/documents/{doc['id']}/retry").status_code == 200  # file is still stored
    ready_lib = client.post(f"{API}/collections", json={"name": "Fine"}).json()
    ok = client.post(f"{API}/collections/{ready_lib['id']}/documents", json={
        "name": "ok.txt", "content_base64": base64.b64encode(b"fine text").decode()}).json()[0]
    wait_ready(client, ready_lib["id"], 1)
    assert client.post(f"{API}/documents/{ok['id']}/retry").status_code == 409  # only failed ones


def test_oversized_upload_is_refused_without_reading_it_into_memory(client, monkeypatch):
    from starlette.datastructures import UploadFile

    reads = []
    real = UploadFile.read

    async def spy(self, *args, **kwargs):
        reads.append(self.filename)
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(UploadFile, "read", spy)
    lib = client.post(f"{API}/collections", json={"name": "Huge"}).json()
    r = client.post(f"{API}/collections/{lib['id']}/documents",
                    files=[("file", ("huge.txt", b"a" * (25 * 1024 * 1024 + 1), "text/plain"))])
    assert r.status_code == 422 and "25 MB" in r.json()["detail"]
    assert reads == []


def test_upload_errors(client):
    lib = client.post(f"{API}/collections", json={"name": "Errors"}).json()
    bad = client.post(f"{API}/collections/{lib['id']}/documents", files=[("file", ("a.zip", b"PK\x03\x04zip", "application/zip"))])
    assert bad.status_code == 422 and "isn't supported" in bad.json()["detail"]
    big = client.post(f"{API}/collections/{lib['id']}/documents",
                      files=[("file", ("big.txt", b"a" * (25 * 1024 * 1024 + 1), "text/plain"))])
    assert big.status_code == 422 and "25 MB" in big.json()["detail"]
    assert client.post(f"{API}/collections/999999/documents", files=[("file", ("x.txt", b"x", "text/plain"))]).status_code == 404


def test_chat_collection_upload_isolated(client):
    up = client.post(f"{API}/chats/api-chat-a/documents", files=[("file", ("secret.md", b"# S\n\nThe password is heron.", "text/markdown"))])
    assert up.status_code == 200
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.post(f"{API}/search", json={"query": "password heron", "session_id": "api-chat-a"}).json()["sources"]:
            break
        time.sleep(0.05)
    assert client.post(f"{API}/search", json={"query": "password heron", "session_id": "api-chat-a"}).json()["sources"]
    other_chat = client.post(f"{API}/search", json={"query": "password heron", "session_id": "api-chat-b"}).json()
    assert all(s["document_name"] != "secret.md" for s in other_chat["sources"])
    assert all(not c["name"].startswith("chat:") for c in client.get(f"{API}/collections").json())


def test_old_knowledge_document_routes_gone(client):
    assert client.get("/api/knowledge/documents").status_code == 404
    assert client.get("/api/knowledge/search", params={"q": "x"}).status_code == 404
    assert client.get("/api/knowledge/memories").status_code == 200

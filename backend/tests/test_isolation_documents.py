"""Two accounts: Bo never sees Ana's libraries, documents or passages, by listing, id, search or the agent's tool."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def ana():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def bo():
    with TestClient(app, user="bo@example.com") as c:
        yield c


@pytest.fixture(scope="module")
def anas(ana):
    library = ana.post("/api/rag/collections", json={"name": "Ana's medical records"}).json()
    doc = ana.post(f"/api/rag/collections/{library['id']}/documents",
                   files=[("file", ("blood-test.md", b"# Blood test\nAna's cholesterol is 190 mg/dL, measured in March."))]).json()[0]
    for _ in range(100):
        if ana.get(f"/api/rag/documents/{doc['id']}").json()["status"] in ("ready", "failed"):
            break
        time.sleep(0.1)
    assert ana.get(f"/api/rag/documents/{doc['id']}").json()["status"] == "ready"
    return {"library": library, "doc": doc}


def test_bo_lists_none_of_anas(bo, anas):
    assert anas["library"]["id"] not in [c["id"] for c in bo.get("/api/rag/collections").json()]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/rag/collections/{library}/documents"),
    ("patch", "/api/rag/collections/{library}"),
    ("delete", "/api/rag/collections/{library}"),
    ("get", "/api/rag/documents/{doc}"),
    ("delete", "/api/rag/documents/{doc}"),
    ("post", "/api/rag/documents/{doc}/retry"),
])
def test_bo_cannot_reach_anas_by_id(bo, anas, method, path):
    url = path.format(library=anas["library"]["id"], doc=anas["doc"]["id"])
    kwargs = {"json": {"name": "mine now"}} if method == "patch" else {}
    assert getattr(bo, method)(url, **kwargs).status_code == 404, url


def test_search_only_finds_your_own(ana, bo, anas):
    assert "cholesterol" in str(ana.post("/api/rag/search", json={"query": "cholesterol"}).json())
    assert "cholesterol" not in str(bo.post("/api/rag/search", json={"query": "cholesterol"}).json())
    assert "cholesterol" not in str(bo.post("/api/rag/search", json={"query": "cholesterol",
                                                                      "collection_ids": [anas["library"]["id"]]}).json())


def test_the_agents_document_tool_only_finds_your_own(bo, anas):
    from app.auth import store
    from app.auth.owner import as_user
    from app.tools import get_tool_registry

    tool = get_tool_registry().get_tool("nexus__search_documents")
    with as_user(store._row("email = ?", "bo@example.com")["id"]):
        import asyncio

        found = asyncio.run(tool.execute({"query": "cholesterol"}))
    assert "cholesterol" not in str(found)

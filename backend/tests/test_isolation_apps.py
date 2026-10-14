"""Two accounts: Bo never sees or uses Ana's MCP servers, integrations, AI providers (or their keys) or files."""
from __future__ import annotations

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
    server = ana.post("/api/mcp/servers", json={"name": "Ana's Notion", "transport": "http",
                                                 "url": "https://mcp.example.org/notion"}).json()
    provider = ana.post("/api/llm/", json={"provider_name": "openai", "api_key": "sk-ana-secret", "model": "gpt-4o-mini"})
    assert provider.status_code in (200, 201), provider.text
    upload = ana.post("/api/files", files=[("file", ("ana-notes.txt", b"Ana's private notes"))]).json()[0]
    yield {"server": server, "provider": provider.json(), "file": upload}
    ana.delete(f"/api/mcp/servers/{server['id']}")


def test_bo_lists_none_of_anas(bo, anas):
    assert anas["server"]["id"] not in [s["id"] for s in bo.get("/api/mcp/servers").json()]
    assert anas["provider"]["id"] not in [p["id"] for p in bo.get("/api/llm/").json()]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/mcp/servers/{server}"),
    ("patch", "/api/mcp/servers/{server}"),
    ("delete", "/api/mcp/servers/{server}"),
    ("get", "/api/llm/{provider}"),
    ("put", "/api/llm/{provider}"),
    ("delete", "/api/llm/{provider}"),
    ("get", "/api/files/{file_id}/{file_name}"),
    ("get", "/api/files/{file_id}/{file_name}/preview"),
])
def test_bo_cannot_reach_anas_by_id(bo, anas, method, path):
    url = path.format(server=anas["server"]["id"], provider=anas["provider"]["id"],
                      file_id=anas["file"]["id"], file_name=anas["file"]["name"])
    kwargs = {"json": {"name": "mine now", "model": "x"}} if method in ("patch", "put") else {}
    assert getattr(bo, method)(url, **kwargs).status_code == 404, url


def test_bo_never_chats_on_anas_ai_key(bo, anas):
    """With no AI provider of his own, Bo is told to add one: Ana's key (and her bill) is never used for him."""
    from app.auth import store
    from app.auth.owner import as_user
    from app.llm.utils import get_default_llm_provider

    with as_user(store._row("email = ?", "bo@example.com")["id"]):
        provider, config = get_default_llm_provider()
    assert provider is None or (config or {}).get("id") != anas["provider"]["id"]


def test_ana_still_has_hers(ana, anas):
    assert anas["server"]["id"] in [s["id"] for s in ana.get("/api/mcp/servers").json()]
    assert ana.get(anas["file"]["url"]).content == b"Ana's private notes"

"""Marketplace logos: the listing's own icon, else the GitHub owner's avatar, else the domain's favicon; cached."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.mcp import icons, registry

OFFICIAL = "io.modelcontextprotocol.registry/official"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


def listing(name, **server):
    return {"server": {"name": name, "description": "d", "version": "1",
                       "remotes": [{"type": "streamable-http", "url": "https://h.example/mcp"}], **server},
            "_meta": {OFFICIAL: {"status": "active", "isLatest": True}}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "icon_dir", lambda: tmp_path)
    with TestClient(app) as c:
        conn = get_connection()
        for table in ("registry_servers", "registry_fts", "registry_sync"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        servers = [listing("com.acme/tool", icons=[{"src": "https://acme.com/logo.png"}]),
                   listing("io.github.jane/tool"), listing("com.plain/tool"), listing("com.nothing/tool")]
        asyncio.run(registry.sync(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"servers": servers, "metadata": {}}))))
        yield c


def web(routes):
    """Fake internet: url prefix -> response; records every request."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response()
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def png():
    return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})


def get(client, name):
    return client.get("/api/marketplace/icon", params={"name": name})


def test_own_icon_first(client, monkeypatch):
    transport, seen = web({"https://acme.com/logo.png": png})
    monkeypatch.setattr(icons, "TRANSPORT", transport)
    response = get(client, "com.acme/tool")
    assert response.status_code == 200 and response.content == PNG and response.headers["content-type"] == "image/png"
    assert seen == ["https://acme.com/logo.png"]


def test_github_avatar_then_domain_favicon(client, monkeypatch):
    transport, seen = web({"https://github.com/jane.png": png, "https://icons.duckduckgo.com/ip3/plain.com.ico": png})
    monkeypatch.setattr(icons, "TRANSPORT", transport)
    assert get(client, "io.github.jane/tool").status_code == 200
    assert get(client, "com.plain/tool").status_code == 200
    assert seen[0].startswith("https://github.com/jane.png") and seen[1] == "https://icons.duckduckgo.com/ip3/plain.com.ico"


def test_cached_and_misses_remembered(client, monkeypatch):
    transport, seen = web({"https://acme.com/logo.png": png})
    monkeypatch.setattr(icons, "TRANSPORT", transport)
    get(client, "com.acme/tool")
    assert get(client, "com.nothing/tool").status_code == 404
    count = len(seen)
    assert get(client, "com.acme/tool").status_code == 200  # from disk
    assert get(client, "com.nothing/tool").status_code == 404  # remembered: no new lookups
    assert len(seen) == count


def test_rejects_non_images_and_oversized(client, monkeypatch):
    transport, _ = web({
        "https://acme.com/logo.png": lambda: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        "https://icons.duckduckgo.com/ip3/acme.com.ico": lambda: httpx.Response(
            200, content=b"0" * (icons.MAX_BYTES + 1), headers={"content-type": "image/png"}),
    })
    monkeypatch.setattr(icons, "TRANSPORT", transport)
    assert get(client, "com.acme/tool").status_code == 404


def test_svg_served_with_script_blocking_header(client, monkeypatch):
    transport, _ = web({"https://acme.com/logo.png": lambda: httpx.Response(
        200, content=b"<svg xmlns='http://www.w3.org/2000/svg'/>", headers={"content-type": "image/svg+xml"})})
    monkeypatch.setattr(icons, "TRANSPORT", transport)
    response = get(client, "com.acme/tool")
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_unknown_listing_is_404(client):
    assert get(client, "io.x/missing").status_code == 404

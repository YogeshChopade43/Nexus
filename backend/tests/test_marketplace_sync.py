"""Marketplace Task 2: the local copy of the MCP Registry (full + incremental sync, failures, odd entries)."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.mcp import registry

OFFICIAL = "io.modelcontextprotocol.registry/official"
HOSTED = {"remotes": [{"type": "streamable-http", "url": "https://h/mcp"}]}
NPM = {"remotes": [{"type": "streamable-http", "url": "https://other.example/mcp"}]}  # a second hosted server
LOCAL = {"packages": [{"registryType": "npm", "identifier": "@x/n", "version": "1.0", "transport": {"type": "stdio"}}]}


def entry(name, status="active", latest=True, **server):
    return {"server": {"name": name, "description": f"about {name}", "version": "1.0", **server},
            "_meta": {OFFICIAL: {"status": status, "updatedAt": "2026-10-01T00:00:00Z", "isLatest": latest}}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    with TestClient(app):
        pass  # runs migrations on the test database
    monkeypatch.setattr(registry, "RETRY_DELAYS", (0, 0, 0))
    conn = get_connection()
    for table in ("registry_servers", "registry_fts", "registry_sync"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def run(handler):
    return asyncio.run(registry.sync(transport=httpx.MockTransport(handler)))


def page(servers, cursor=None):
    return httpx.Response(200, json={"servers": servers, "metadata": {"count": len(servers), **({"nextCursor": cursor} if cursor else {})}})


def test_full_sync_pages():
    def handler(request):
        if request.url.params.get("cursor") == "p2":
            return page([entry("io.x/c", **NPM)])
        return page([entry("io.x/a", **HOSTED), entry("io.x/b", **NPM)], cursor="p2")

    status = run(handler)
    assert status["status"] == "idle" and status["count"] == 3
    assert registry.get_row("io.x/a")["install"]["kind"] == "hosted"


def test_incremental_uses_updated_since_and_deletes():
    run(lambda request: page([entry("io.x/a", **HOSTED), entry("io.x/b", **NPM)]))
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return page([entry("io.x/a", status="deleted", **HOSTED)])

    run(handler)
    assert "updated_since" in seen[0]
    assert registry.get_row("io.x/a") is None and registry.get_row("io.x/b") is not None


def test_failed_page_keeps_rows():
    run(lambda request: page([entry("io.x/a", **HOSTED)]))
    status = run(lambda request: httpx.Response(500, text="boom"))
    assert status["status"] == "error" and status["error"]
    assert registry.get_row("io.x/a") is not None


def test_sync_tolerates_odd_entries():
    odd = [
        {"server": {"name": "io.x/untitled", "title": None, "version": "1", **HOSTED}, "_meta": {}},
        entry("io.x/sse", remotes=[{"type": "sse", "url": "https://s/sse"}]),
        entry("io.x/nuget", packages=[{"registryType": "nuget", "identifier": "n"}]),
        entry("io.x/nothing"),
        entry("io.x/old", latest=False, **HOSTED),
    ]
    status = run(lambda request: page(odd))
    assert status["status"] == "idle" and status["count"] == 1
    assert registry.get_row("io.x/untitled")["description"] == ""


def test_deleted_old_version_keeps_the_current_listing():
    run(lambda request: page([entry("io.x/a", **HOSTED)]))
    old = entry("io.x/a", status="deleted", latest=False, **HOSTED)
    old["server"]["version"] = "0.9"
    run(lambda request: page([old]))
    assert registry.get_row("io.x/a") is not None


def test_one_malformed_entry_does_not_stop_the_sync():
    bad = entry("io.x/bad", **HOSTED)
    bad["server"]["repository"] = "https://github.com/x/bad"  # a string where an object is expected
    bad["server"]["icons"] = ["x.png"]
    status = run(lambda request: page([bad, entry("io.x/good", **NPM)]))
    assert status["status"] == "idle" and registry.get_row("io.x/good") is not None


def test_local_listings_are_not_kept():
    status = run(lambda request: page([entry("io.x/hosted", **HOSTED), entry("io.x/local", **LOCAL)]))
    assert status["count"] == 1 and registry.get_row("io.x/local") is None

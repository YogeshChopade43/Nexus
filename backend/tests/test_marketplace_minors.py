"""Marketplace review follow-ups (M-1, M-2, M-6, M-9, M-10)."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.mcp import registry, store

OFFICIAL = "io.modelcontextprotocol.registry/official"


def listing(name, title, description="A perfectly ordinary helpful server"):
    return {"server": {"name": name, "title": title, "description": description, "version": "1",
                       "remotes": [{"type": "streamable-http", "url": f"https://{name.split('/')[0]}.example/mcp"}]},
            "_meta": {OFFICIAL: {"status": "active", "isLatest": True}}}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(registry, "RETRY_DELAYS", (0, 0, 0))
    with TestClient(app) as c:
        conn = get_connection()
        for table in ("registry_servers", "registry_fts", "registry_sync"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM mcp_servers WHERE registry_name != ''")
        conn.commit()
        conn.close()
        yield c


def sync(servers):
    return asyncio.run(registry.sync(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"servers": servers, "metadata": {}}))))


def test_m1_sync_that_fails_before_starting_does_not_stay_syncing(client, monkeypatch):
    def broken(conn):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(registry, "_sync_row", broken)
    with pytest.raises(RuntimeError):
        asyncio.run(registry.sync())
    monkeypatch.undo()
    assert registry.status()["status"] != "syncing"


def test_m6_installed_filter_honours_search(client):
    sync([listing("com.alpha/mcp", "Alpha Notes"), listing("com.beta/mcp", "Beta Mail")])
    for name, url in (("Alpha Notes", "https://com.alpha.example/mcp"), ("Beta Mail", "https://com.beta.example/mcp")):
        store.create_server({"name": name, "transport": "http", "url": url, "enabled": False})
    cards = client.get("/api/marketplace", params={"kind": "installed", "q": "mail"}).json()["items"]
    assert [c["title"] for c in cards] == ["Beta Mail"]


def test_m9_stop_cancels_a_running_sync(client):
    async def scenario():
        started = asyncio.Event()

        async def slow(request):
            started.set()
            await asyncio.sleep(30)
            return httpx.Response(200, json={"servers": [], "metadata": {}})

        registry._task = asyncio.get_running_loop().create_task(registry.sync(transport=httpx.MockTransport(slow)))
        await asyncio.wait_for(started.wait(), 5)
        await registry.stop_sync()
        assert registry._task.done() and not registry._running

    asyncio.run(scenario())


def test_m10_search_survives_vacuum_after_deletions(client):
    sync([listing("com.a/mcp", "Aardvark"), listing("com.b/mcp", "Badger"), listing("com.c/mcp", "Cheetah")])
    sync([{**listing("com.a/mcp", "Aardvark"), "_meta": {OFFICIAL: {"status": "deleted", "isLatest": True}}}])
    conn = get_connection()
    conn.isolation_level = None
    conn.execute("VACUUM")
    conn.close()
    titles = [c["title"] for c in client.get("/api/marketplace", params={"q": "cheetah"}).json()["items"]]
    assert titles == ["Cheetah"]

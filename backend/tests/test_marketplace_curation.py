"""Marketplace front page: a Featured shelf, and test/staging, empty and duplicate listings kept out of the way."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.mcp import registry

OFFICIAL = "io.modelcontextprotocol.registry/official"
HOSTED = {"remotes": [{"type": "streamable-http", "url": "https://h.example/mcp"}]}


def listing(name, title="", description="Does a useful thing for your workspace", updated="2026-10-01T00:00:00Z"):
    return {"server": {"name": name, "title": title, "description": description, "version": "1", **HOSTED},
            "_meta": {OFFICIAL: {"status": "active", "isLatest": True, "updatedAt": updated}}}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(registry, "FEATURED", ("com.notion/mcp", "io.github.github/github-mcp-server", "com.gone/mcp"))
    with TestClient(app) as c:
        conn = get_connection()
        for table in ("registry_servers", "registry_fts", "registry_sync"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        servers = [
            listing("com.notion/mcp"), listing("io.github.github/github-mcp-server", "GitHub"),
            listing("com.amy/weather", "Weather"),
            listing("com.bob/test-server", "Test server"),                  # test listing
            listing("live.alpic.staging.everything/app", "Everything"),     # staging namespace
            listing("com.cat/thing", "(WiP) Thing"),                        # work in progress
            listing("com.dan/hex", "16 hex chars", description="16 hex chars"),  # no real description
            listing("com.eve/faf", "FAF Context", updated="2026-09-01T00:00:00Z"),
            listing("com.eve/faf-ide", "FAF Context", updated="2026-10-05T00:00:00Z"),  # same publisher: newer kept
            listing("one.faf/faf", "FAF Context"),                          # another publisher: kept
        ]
        asyncio.run(registry.sync(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"servers": servers, "metadata": {}}))))
        yield c


def names(client, **params):
    return [c["name"] for c in client.get("/api/marketplace", params={"limit": 100, **params}).json()["items"]]


def test_featured_in_order_and_skips_missing(client):
    featured = [c["name"] for c in client.get("/api/marketplace/featured").json()["items"]]
    assert featured == ["com.notion/mcp", "io.github.github/github-mcp-server"]


def test_junk_is_off_the_front_page_and_last_in_search(client):
    shown = names(client)
    for junk in ("com.bob/test-server", "live.alpic.staging.everything/app", "com.cat/thing", "com.dan/hex"):
        assert junk not in shown
    assert "com.amy/weather" in shown
    # Search still finds them (a false positive stays reachable), after everything else.
    found = names(client, q="thing")
    assert found.index("com.amy/weather") < found.index("com.cat/thing")


def test_flags_backfilled_for_rows_stored_before(client):
    conn = get_connection()
    conn.execute("UPDATE registry_servers SET junk = NULL, official = NULL")
    conn.commit()
    conn.close()
    registry.backfill_flags()
    assert "com.bob/test-server" not in names(client)


def test_same_publisher_duplicates_keep_the_newest(client):
    shown = names(client, q="faf")
    assert "com.eve/faf-ide" in shown and "com.eve/faf" not in shown
    assert "one.faf/faf" in shown  # a different publisher's listing is not a duplicate

"""Marketplace Task 3: search, listing details, install, and matching servers that are already installed."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import marketplace as route
from app.core.database import get_connection
from app.main import app
from app.mcp import registry, store

OFFICIAL = "io.modelcontextprotocol.registry/official"
API = "/api/marketplace"
LISTINGS = [
    {"server": {"name": "io.x/hosted", "title": "Hosted Thing", "description": "A hosted helper for invoices",
                "version": "1", "remotes": [{"type": "streamable-http", "url": "https://hosted.example/mcp",
                                             "headers": [{"name": "Authorization", "value": "Bearer {api_key}",
                                                          "isRequired": True, "isSecret": True}]}]},
     "_meta": {OFFICIAL: {"status": "active", "updatedAt": "2026-10-02T00:00:00Z", "isLatest": True}}},
    {"server": {"name": "io.x/files", "description": "Read files from a zebra folder", "version": "1.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://files.example/mcp",
                             "headers": [{"name": "X-Token", "value": "{TOKEN}", "isRequired": True, "isSecret": True}]}]},
     "_meta": {OFFICIAL: {"status": "active", "updatedAt": "2026-10-01T00:00:00Z", "isLatest": True}}},
]


@pytest.fixture()
def client(monkeypatch):
    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(route.mcp_manager, "apply", nothing)  # don't dial out in tests
    monkeypatch.setattr(route.mcp_manager, "wait_ready", nothing)
    with TestClient(app) as c:
        conn = get_connection()
        for table in ("registry_servers", "registry_fts", "registry_sync"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM mcp_servers WHERE registry_name != '' OR name IN ('Files', 'Hosted Thing', 'files')")
        conn.commit()
        conn.close()
        response = httpx.Response(200, json={"servers": LISTINGS, "metadata": {"count": 2}})
        asyncio.run(registry.sync(transport=httpx.MockTransport(lambda request: response)))
        yield c


def names(response):
    return [card["name"] for card in response.json()["items"]]


def test_search_matches_description_and_filters(client):
    assert "io.x/files" in names(client.get(API, params={"q": "zebra"}))
    assert client.get(API).json()["status"]["count"] == 2


def test_search_survives_fts_syntax(client):
    for query in ['"', "*", "-x", "OR (", "a AND"]:
        response = client.get(API, params={"q": query})
        assert response.status_code == 200 and isinstance(response.json()["items"], list)


def test_item_detail_has_fields(client):
    item = client.get(f"{API}/item", params={"name": "io.x/hosted"}).json()
    assert item["fields"][0]["key"] == "api_key" and item["installed"] is None
    assert item["title"] == "Hosted Thing" and item["publisher"] == "x.io"
    assert client.get(f"{API}/item", params={"name": "io.x/nope"}).status_code == 404


def test_install_hosted_and_mark_installed(client):
    missing = client.post(f"{API}/install", json={"name": "io.x/hosted", "values": {}})
    assert missing.status_code == 422 and "api_key is required" in missing.json()["detail"]
    installed = client.post(f"{API}/install", json={"name": "io.x/hosted", "values": {"api_key": "k"}})
    assert installed.status_code == 200, installed.text
    server_id = installed.json()["id"]
    cards = {c["name"]: c for c in client.get(API, params={"kind": "installed"}).json()["items"]}
    assert cards["io.x/hosted"]["installed_server_id"] == server_id
    assert client.post(f"{API}/install", json={"name": "io.x/hosted", "values": {"api_key": "k"}}).status_code == 409


def test_install_masks_secrets(client):
    installed = client.post(f"{API}/install", json={"name": "io.x/files", "values": {"TOKEN": "s3cret"}})
    assert installed.status_code == 200, installed.text
    assert "s3cret" not in installed.text
    assert "s3cret" not in client.get(f"{API}/item", params={"name": "io.x/files"}).text


def test_existing_server_matched_by_url(client):
    server = store.create_server({"name": "files", "transport": "http", "url": "https://files.example/mcp",
                                  "enabled": False})
    card = next(c for c in client.get(API).json()["items"] if c["name"] == "io.x/files")
    assert card["installed_server_id"] == server.id


def test_failed_install_never_echoes_secrets(client):
    listing = {"server": {"name": "io.x/based", "description": "Needs a base URL", "version": "1",
                          "remotes": [{"type": "streamable-http", "url": "{base_url}/mcp",
                                       "headers": [{"name": "Authorization", "value": "Bearer {api_key}", "isSecret": True}]}]},
               "_meta": {OFFICIAL: {"status": "active", "isLatest": True}}}
    asyncio.run(registry.sync(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"servers": [listing], "metadata": {}}))))
    response = client.post(f"{API}/install", json={"name": "io.x/based", "values": {"base_url": "not-a-url", "api_key": "s3cret"}})
    assert response.status_code == 422 and "s3cret" not in response.text


def test_item_shows_what_will_run(client):
    launch = client.get(f"{API}/item", params={"name": "io.x/files"}).json()["launch"]
    assert launch == {"url": "https://files.example/mcp", "headers": {"X-Token": "{TOKEN}"}}
    assert client.get(f"{API}/item", params={"name": "io.x/hosted"}).json()["launch"]["url"] == "https://hosted.example/mcp"


def test_installed_cards_carry_status(client):
    client.post(f"{API}/install", json={"name": "io.x/hosted", "values": {"api_key": "k"}})
    card = next(c for c in client.get(API).json()["items"] if c["name"] == "io.x/hosted")
    assert card["status"] is not None
    assert next(c for c in client.get(API).json()["items"] if c["name"] == "io.x/files")["status"] is None


def test_install_does_not_wait_for_a_slow_first_launch(client, monkeypatch):
    waits = []

    async def wait_ready(server_id, timeout=60):
        waits.append(timeout)

    monkeypatch.setattr(route.mcp_manager, "wait_ready", wait_ready)
    client.post(f"{API}/install", json={"name": "io.x/files", "values": {"TOKEN": "t"}})
    assert waits and waits[0] <= 10  # a slow server doesn't keep Install spinning; the panel follows the status

"""MCP server extras: logs and health, tool-list refresh, OAuth sign-in glue, and schema migrations."""
from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.core.database import MIGRATIONS, get_db_path, run_migrations
from app.main import app
from app.mcp import mcp_manager, store
from app.mcp.manager import _Runtime, _TokenStorage
from mcp.shared.auth import OAuthToken

from tests.test_nexus import STDIO_SERVER


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def server(client):
    r = client.post("/api/mcp/servers", json={**STDIO_SERVER, "name": "Logs"})
    assert r.status_code == 200 and r.json()["status"] == "connected", r.text
    yield r.json()
    client.delete(f"/api/mcp/servers/{r.json()['id']}")


def _call(client, tool, parameters):
    node = {"id": "a", "type": "action", "name": "a", "config": {"tool": tool, "parameters": parameters}}
    r = client.post("/api/workflows/test-step", json={"node": node})
    assert r.status_code == 200, r.text
    return r.json()


def _wait(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_logs_and_health(client, server):
    logs = client.get(f"/api/mcp/servers/{server['id']}/logs").json()
    assert any(e["message"].startswith("Connected") for e in logs["events"])
    assert _wait(lambda: "echo fixture starting" in client.get(f"/api/mcp/servers/{server['id']}/logs").json()["stderr"])

    _call(client, "logs__echo", {"text": "hi"})
    health = client.get(f"/api/mcp/servers/{server['id']}").json()["health"]
    assert health["calls"] == 1 and health["failures"] == 0 and health["connected_since"]


def test_tool_list_change_is_picked_up(client, server):
    names = lambda: [t["name"] for t in client.get(f"/api/mcp/servers/{server['id']}").json()["tools"]]  # noqa: E731
    assert "logs__extra" not in names()
    _call(client, "logs__grow", {})
    assert _wait(lambda: "logs__extra" in names()), names()


def test_oauth_redirect_and_callback(client):
    """The SDK's redirect/callback hooks wait for /oauth/callback to deliver the code."""
    config = store.create_server({"name": "Hosted", "transport": "http", "url": "https://example.invalid/mcp", "enabled": False})

    async def flow():
        runtime = _Runtime(config=config)
        mcp_manager._runtimes[config.id] = runtime
        try:
            provider = mcp_manager._oauth(runtime)
            await provider.context.redirect_handler("https://auth.example/authorize?client_id=x&state=abc123")
            assert runtime.status == "needs_auth" and runtime.auth_url.startswith("https://auth.example/")
            assert mcp_manager.complete_sign_in("wrong", "code") is False
            waiting = asyncio.create_task(provider.context.callback_handler())
            await asyncio.sleep(0)
            assert mcp_manager.complete_sign_in("abc123", "the-code") is True
            result = await waiting
            assert (result.code, result.state) == ("the-code", "abc123")
            assert runtime.status == "connecting" and runtime.auth_url is None

            storage = _TokenStorage(config.id)
            assert await storage.get_tokens() is None
            await storage.set_tokens(OAuthToken(access_token="tok", refresh_token="ref"))
            assert (await storage.get_tokens()).access_token == "tok"
        finally:
            mcp_manager._runtimes.pop(config.id, None)

    asyncio.run(flow())
    assert store.get_server(config.id).signed_in
    raw = sqlite3.connect(get_db_path()).execute("SELECT oauth FROM mcp_servers WHERE id = ?", (config.id,)).fetchone()[0]
    assert raw.startswith("fernet:") and "tok" not in raw  # tokens are encrypted at rest

    page = client.get("/api/mcp/servers/oauth/callback", params={"code": "c", "state": "nobody-waiting"})
    assert page.status_code == 200 and "expired" in page.text
    assert client.post(f"/api/mcp/servers/{config.id}/sign-out").json()["signed_in"] is False
    client.delete(f"/api/mcp/servers/{config.id}")


def test_migrations_run_once(client):
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not {"users", "user_sessions", "audit_log"} & tables  # login was removed (migration 4)
        run_migrations(conn)  # already applied: nothing to do, no "duplicate column" error
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        conn.close()


def test_tool_view_has_display_hints(client, server):
    tools = {t["remote_name"]: t for t in client.get(f"/api/mcp/servers/{server['id']}").json()["tools"]}
    assert tools["echo"]["required"] == ["text"] and tools["list_items"]["required"] == []
    assert {"title", "read_only", "destructive"} <= tools["echo"].keys()


def test_sign_in_passes_the_issuer_through(client, monkeypatch):
    """RFC 9207 servers (hosted Notion) send iss with the code; the SDK refuses the sign-in without it."""
    config = store.create_server({"name": "Issuer", "transport": "http", "url": "https://example.invalid/mcp", "enabled": False})

    async def flow():
        runtime = _Runtime(config=config)
        mcp_manager._runtimes[config.id] = runtime
        try:
            provider = mcp_manager._oauth(runtime)
            await provider.context.redirect_handler("https://auth.example/authorize?state=s1")
            waiting = asyncio.create_task(provider.context.callback_handler())
            await asyncio.sleep(0)
            assert mcp_manager.complete_sign_in("s1", "code", iss="https://auth.example") is True
            assert (await waiting).iss == "https://auth.example"
        finally:
            mcp_manager._runtimes.pop(config.id, None)

    asyncio.run(flow())
    client.delete(f"/api/mcp/servers/{config.id}")

    seen = []
    monkeypatch.setattr(mcp_manager, "complete_sign_in", lambda state, code, iss=None: seen.append((state, code, iss)) or True)
    page = client.get("/api/mcp/servers/oauth/callback", params={"code": "c", "state": "s", "iss": "https://auth.example"})
    assert "Signed in" in page.text and seen == [("s", "c", "https://auth.example")]


def test_failed_local_server_says_why(client):
    """'Connection closed' alone is useless: the server's own last error line explains it (a missing API key)."""
    import sys

    from app.mcp.manager import server_said

    script = "import sys; print('starting up', file=sys.stderr); print('Error: FOO_API_KEY environment variable is required', file=sys.stderr); sys.exit(1)"
    created = client.post("/api/mcp/servers/", json={"name": "Says Why", "transport": "stdio",
                                                      "command": sys.executable, "args": ["-c", script]}).json()
    try:
        assert created["status"] == "error"
        assert "FOO_API_KEY environment variable is required" in created["error"]
        assert server_said(created["slug"]) == "Error: FOO_API_KEY environment variable is required"
    finally:
        client.delete(f"/api/mcp/servers/{created['id']}")


def test_local_servers_are_refused(client, monkeypatch):
    """Nexus connects to hosted servers only; it never launches programs on this computer."""
    monkeypatch.delenv("NEXUS_ALLOW_LOCAL_SERVERS", raising=False)
    response = client.post("/api/mcp/servers/", json={"name": "Local", "transport": "stdio", "command": "npx", "args": ["x"]})
    assert response.status_code == 422 and "hosted" in response.json()["detail"]
    hosted = client.post("/api/mcp/servers/", json={"name": "Remote", "transport": "http",
                                                     "url": "https://example.invalid/mcp", "enabled": False})
    assert hosted.status_code == 200
    assert client.patch(f"/api/mcp/servers/{hosted.json()['id']}", json={"transport": "stdio", "command": "npx"}).status_code == 422
    client.delete(f"/api/mcp/servers/{hosted.json()['id']}")

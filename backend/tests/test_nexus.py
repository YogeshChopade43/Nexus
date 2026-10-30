"""End-to-end API tests against a throwaway database and a real MCP fixture server.

Run: ``.venv311\\Scripts\\python -m pytest tests``
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
STDIO_SERVER = {
    "name": "Echo",
    "transport": "stdio",
    "command": sys.executable,
    "args": [FIXTURE],
    "env": {"ECHO_SECRET": "s3"},
}


class FakeLLM:
    provider_name = "fake"
    default_model = "fake"

    def __init__(self):
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return {"content": f"reply to: {messages[-1]['content']}"}

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(messages)
        if messages[-1]["role"] == "tool":
            return {"content": "Found 3 items.", "tool_calls": []}
        if "items" in messages[-1]["content"]:
            return {"content": "", "tool_calls": [{"id": "t1", "name": "echo__list_items", "arguments": '{"count": 3}'}]}
        return {"content": "plain answer", "tool_calls": []}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def echo(client):
    r = client.post("/api/mcp/servers", json=STDIO_SERVER)
    assert r.status_code == 200, r.text
    server = r.json()
    assert server["status"] == "connected", server
    return server


def test_stdio_server_tools_and_secrets(client, echo):
    assert echo["slug"] == "echo"
    assert echo["env"] == {"ECHO_SECRET": "***"}
    names = {t["name"] for t in echo["tools"]}
    assert {"echo__echo", "echo__list_items", "echo__fail"} <= names

    tools = {t["tool_name"]: t for t in client.get("/api/tools/").json()["tools"]}
    assert tools["echo__list_items"]["available"] is True
    assert tools["echo__list_items"]["parameters"]["properties"]["count"]["type"] == "integer"
    assert "echo__echo" in client.get("/api/tools/available").json()["tools"]


def test_agent_calls_mcp_tool_with_session_history(client, echo, monkeypatch):
    llm = FakeLLM()
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (llm, {}))

    session_id = client.post("/api/agent/sessions", json={}).json()["session_id"]
    body = client.post("/api/agent/run", json={"message": "list items please", "session_id": session_id}).json()
    assert body["response"] == "Found 3 items.", body
    executed = [e for e in body["events"] if e["type"] == "tool_executed"]
    assert executed and executed[0]["tool_name"] == "echo__list_items"
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "t1" and '"items": [0, 1, 2]' in tool_msg["content"]

    client.post("/api/agent/run", json={"message": "and again?", "session_id": session_id})
    sent = [(m["role"], m["content"]) for m in llm.calls[-1][1:]]
    assert [role for role, _ in sent] == ["user", "assistant", "user"]
    assert sent[0][1] == "list items please" and sent[2][1] == "and again?"
    # The earlier reply carries what its tool returned, so a follow-up can use it.
    assert sent[1][1].startswith("Found 3 items.") and "echo__list_items" in sent[1][1] and '"items": [0, 1, 2]' in sent[1][1]
    assert client.get("/api/activity", params={"types": "message_received"}).json()["total"] >= 2


def _workflow(client, nodes, edges, name="wf"):
    r = client.post("/api/workflows", json={"name": name, "nodes": nodes, "edges": edges, "isActive": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_workflow_with_mcp_actions(client, echo):
    nodes = [
        {"id": "a", "type": "action", "name": "Items", "config": {"tool": "echo__list_items", "parameters": {"count": "{{ input.n }}"}}},
        {"id": "c", "type": "condition", "name": "Many?", "config": {"field": "steps.a.data.items", "operator": "not_empty"}},
        {"id": "yes", "type": "action", "name": "Say", "config": {"tool": "echo__echo", "parameters": {"text": "{{ steps.a.data.items | length }} items"}}},
        {"id": "no", "type": "transform", "name": "No", "config": {"template": "none"}},
    ]
    edges = [
        {"id": "e1", "source": "a", "target": "c"},
        {"id": "e2", "source": "c", "target": "yes", "sourceHandle": "true"},
        {"id": "e3", "source": "c", "target": "no", "sourceHandle": "false"},
    ]
    wf = _workflow(client, nodes, edges)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"input_data": {"n": 2}}).json()
    assert run["status"] == "completed", run
    by_node = {e["nodeId"]: e for e in run["events"]}
    assert by_node["yes"]["output"]["text"] == "echo: 2 items"
    assert by_node["no"]["status"] == "skipped"

    nodes[0]["config"] = {"tool": "echo__fail"}
    client.patch(f"/api/workflows/{wf['id']}", json={"nodes": nodes, "edges": edges})
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "failed" and run["error"].startswith("Items:")


def test_secret_kept_on_update_and_disable_removes_tools(client, echo):
    r = client.patch(f"/api/mcp/servers/{echo['id']}", json={"env": {"ECHO_SECRET": "***"}, "args": [FIXTURE]})
    assert r.json()["status"] == "connected"
    wf = _workflow(client, [{"id": "a", "type": "action", "config": {"tool": "echo__list_items"}}], [], name="secret")
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["events"][0]["output"]["data"]["env_seen"] == "s3"

    r = client.patch(f"/api/mcp/servers/{echo['id']}", json={"enabled": False})
    assert r.json()["status"] == "stopped"
    assert not [t for t in client.get("/api/tools/available").json()["tools"] if t.startswith("echo__")]
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "failed"

    r = client.patch(f"/api/mcp/servers/{echo['id']}", json={"enabled": True})
    assert r.json()["status"] == "connected"


def test_bad_command_reports_error(client):
    r = client.post("/api/mcp/servers", json={"name": "Broken", "transport": "stdio", "command": "definitely-not-a-command-xyz"})
    server = r.json()
    assert server["status"] == "error" and server["error"]
    assert client.delete(f"/api/mcp/servers/{server['id']}").status_code == 204


def test_validation_and_localhost_guard(client, monkeypatch):
    assert client.post("/api/mcp/servers", json={"name": "x", "transport": "http", "url": "ftp://nope"}).status_code == 422
    assert client.post("/api/mcp/servers", json={"name": "x", "transport": "stdio"}).status_code == 422
    monkeypatch.setenv("NEXUS_ALLOW_REMOTE_STDIO", "false")
    r = client.post("/api/mcp/servers", json={**STDIO_SERVER, "name": "Remote attempt"})
    assert r.status_code == 403


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_server(client):
    port = _free_port()
    proc = subprocess.Popen([sys.executable, FIXTURE, "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        r = client.post("/api/mcp/servers", json={
            "name": "Remote echo", "transport": "http", "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": "Bearer abc"},
        })
        server = r.json()
        assert server["status"] == "connected", server
        assert server["headers"] == {"Authorization": "***"}
        wf = _workflow(client, [{"id": "a", "type": "action", "config": {"tool": "remote_echo__echo", "parameters": {"text": "hi"}}}], [], name="http")
        run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
        assert run["events"][0]["output"]["text"] == "echo: hi", run
        client.delete(f"/api/mcp/servers/{server['id']}")
    finally:
        proc.terminate()


def test_settings_roundtrip(client):
    assert client.patch("/api/settings/api", json={"timeout": 10}).status_code == 200
    r = client.get("/api/settings")
    assert r.status_code == 200 and r.json()["api"]["timeout"] == 10


def test_webhook_trigger(client):
    wf = _workflow(client, [
        {"id": "t", "type": "trigger", "config": {"trigger_type": "webhook"}},
        {"id": "x", "type": "transform", "config": {"template": "got {{ trigger.payload.msg }}"}},
    ], [{"source": "t", "target": "x"}], name="hook")
    path = wf["trigger_config"]["webhook_path"]
    assert client.post(f"/api/webhooks/workflows/{wf['id']}?token=wrong", json={}).status_code == 403
    assert client.post(path, json={"msg": "hello"}).status_code == 202
    for _ in range(20):
        runs = client.get(f"/api/workflows/{wf['id']}/runs").json()["runs"]
        if runs and runs[0]["status"] != "running":
            break
        time.sleep(0.1)
    assert runs[0]["events"][0]["output"]["value"] == "got hello"


def test_workflow_validation(client):
    r = client.post("/api/workflows", json={"name": "cyc", "nodes": [{"id": "a", "type": "transform"}, {"id": "b", "type": "transform"}],
                                            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]})
    assert r.status_code == 400 and "cycle" in r.json()["detail"]
    r = client.post("/api/workflows", json={"name": "bad cron", "nodes": [
        {"id": "t", "type": "trigger", "config": {"trigger_type": "schedule", "schedule": "not cron"}}], "edges": []})
    assert r.status_code == 400


def test_anthropic_message_conversion():
    from app.llm.providers.anthropic import to_anthropic_messages

    system, messages = to_anthropic_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "t1", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "t2", "arguments": '{"k": 1}'}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": "r1"},
        {"role": "tool", "tool_call_id": "b", "content": "r2"},
    ])
    assert system == "sys"
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["a", "b"]


def test_qualified_names_fit_llm_limits():
    from app.mcp.manager import qualified_name

    assert qualified_name("echo", "list_items") == "echo__list_items"
    assert len(qualified_name("a_very_long_server_slug_x", "x" * 80)) <= 64

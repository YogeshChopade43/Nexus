"""Undo for chat approvals: approved calls are recorded, and the AI-proposed reverse call runs once."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_agent_features import ToolLLM

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={"name": "Undo Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE]})
        assert r.json()["status"] == "connected", r.json()
        c.server_id = r.json()["id"]
        yield c


@pytest.fixture
def llm(monkeypatch):
    fake = ToolLLM(tool="undo_echo__echo")
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (fake, {}))
    return fake


def session(client):
    return client.post("/api/agent/sessions", json={}).json()["session_id"]


def set_policies(client, policies):
    r = client.patch(f"/api/mcp/servers/{client.server_id}", json={"tool_policies": policies})
    assert r.status_code == 200, r.text


def approved_echo(client, llm):
    set_policies(client, {"echo": "ask"})
    sid = session(client)
    client.post("/api/agent/run", json={"message": "echo please", "session_id": sid})
    client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True})
    set_policies(client, {})
    return client.get("/api/activity/", params={"types": "action_approved"}).json()["activities"][0]  # newest first


def count_action_approved(client):
    return len(client.get("/api/activity/", params={"types": "action_approved", "limit": 200}).json()["activities"])


def activity_by_id(client, activity_id):
    return next(a for a in client.get("/api/activity/", params={"limit": 200}).json()["activities"] if a["id"] == activity_id)


def test_approved_call_is_recorded(client, llm):
    before = count_action_approved(client)
    entry = approved_echo(client, llm)
    assert count_action_approved(client) == before + 1
    assert entry["metadata"]["tool"] == "undo_echo__echo" and entry["metadata"]["arguments"] == {"text": "hi"}
    assert entry["metadata"]["app_id"] and "result" in entry["metadata"]


def test_calls_without_approval_are_not_recorded(client, llm):
    set_policies(client, {})
    before = count_action_approved(client)
    client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)})
    assert count_action_approved(client) == before


def test_failed_approved_call_is_not_recorded(client, llm):
    set_policies(client, {"echo": "ask"})
    llm.args = {}  # echo requires "text": the agent records tool_error, not tool_executed
    before = count_action_approved(client)
    sid = session(client)
    client.post("/api/agent/run", json={"message": "echo please", "session_id": sid})
    client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True})
    assert count_action_approved(client) == before
    set_policies(client, {})


class PlainLLM:
    provider_name = "fake"
    default_model = "fake"

    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages, **kwargs):
        return {"content": self.reply}


def fake_ai(monkeypatch, reply):
    from app import undo

    monkeypatch.setattr(undo, "get_default_llm_provider", lambda: (PlainLLM(reply), {}))


def test_plan_returns_reverse_call(client, llm, monkeypatch):
    entry = approved_echo(client, llm)
    fake_ai(monkeypatch, '{"tool": "undo_echo__list_items", "arguments": {"count": 1}, "explanation": "List again"}')
    plan = client.post(f"/api/activity/{entry['id']}/undo/plan").json()
    assert plan == {"tool": "undo_echo__list_items", "arguments": {"count": 1}, "explanation": "List again"}


def test_plan_refuses_impossible_and_other_apps(client, llm, monkeypatch):
    entry = approved_echo(client, llm)
    fake_ai(monkeypatch, '{"impossible": "A sent message cannot be unsent"}')
    r = client.post(f"/api/activity/{entry['id']}/undo/plan")
    assert r.status_code == 400 and "unsent" in r.json()["detail"]
    fake_ai(monkeypatch, '{"tool": "nexus__notify", "arguments": {}, "explanation": "x"}')
    assert client.post(f"/api/activity/{entry['id']}/undo/plan").status_code == 400
    fake_ai(monkeypatch, '{"tool": "undo_echo__no_such_tool", "arguments": {}, "explanation": "x"}')
    assert client.post(f"/api/activity/{entry['id']}/undo/plan").status_code == 400


def test_run_undoes_once(client, llm):
    entry = approved_echo(client, llm)
    body = {"tool": "undo_echo__echo", "arguments": {"text": "undo"}}
    assert client.post(f"/api/activity/{entry['id']}/undo/run", json=body).json()["undone"] is True
    assert client.post(f"/api/activity/{entry['id']}/undo/run", json=body).status_code == 409
    again = activity_by_id(client, entry["id"])
    assert again["metadata"]["undo"] == body and again["metadata"]["undone_at"]
    assert client.get("/api/activity/", params={"types": "action_undone"}).json()["activities"]


def test_run_refuses_tool_from_another_app(client, llm):
    entry = approved_echo(client, llm)
    r = client.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "nexus__notify", "arguments": {}})
    assert r.status_code == 400
    assert "undone_at" not in activity_by_id(client, entry["id"])["metadata"]


def test_undo_with_disconnected_app_stays_undoable(client, llm, monkeypatch):
    entry = approved_echo(client, llm)
    monkeypatch.setattr("app.undo.server_availability", lambda: {})
    r = client.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "undo_echo__echo", "arguments": {"text": "x"}})
    assert r.status_code == 400 and "not connected" in r.json()["detail"]
    assert "undone_at" not in activity_by_id(client, entry["id"])["metadata"]


def test_other_users_entry_is_404(client, llm):
    entry = approved_echo(client, llm)
    with TestClient(app, user="bo@example.com") as bo:
        assert bo.post(f"/api/activity/{entry['id']}/undo/plan").status_code == 404
        assert bo.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "undo_echo__echo", "arguments": {}}).status_code == 404


def test_only_action_approved_entries_can_be_undone(client):
    other = client.get("/api/activity/", params={"limit": 200}).json()["activities"]
    entry = next(a for a in other if a["type"] != "action_approved")
    assert client.post(f"/api/activity/{entry['id']}/undo/plan").status_code == 404


def test_undo_arguments_are_sent_as_given(client, llm):
    entry = approved_echo(client, llm)
    r = client.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "undo_echo__echo", "arguments": {"text": "{{ not a template }}"}})
    assert "{{ not a template }}" in json.dumps(r.json()["result"])


def test_undo_claims_the_entry_while_it_runs(client, llm, monkeypatch):
    from app import undo
    from app.core.database import get_connection

    entry = approved_echo(client, llm)
    seen = {}

    async def check_claim(e, tool, arguments):
        conn = get_connection()
        try:
            row = conn.execute("SELECT metadata FROM activity_log WHERE id = ?", (int(entry["id"]),)).fetchone()
        finally:
            conn.close()
        seen["metadata"] = json.loads(row["metadata"])
        return {"ok": True}
    monkeypatch.setattr(undo, "run_undo", check_claim)
    client.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "undo_echo__echo", "arguments": {}})
    assert seen["metadata"].get("undoing")  # a second request now gets 409


def test_failed_undo_releases_the_claim(client, llm, monkeypatch):
    from app import undo

    entry = approved_echo(client, llm)

    async def fail(e, tool, arguments):
        raise RuntimeError("the app said no")
    monkeypatch.setattr(undo, "run_undo", fail)
    assert client.post(f"/api/activity/{entry['id']}/undo/run", json={"tool": "undo_echo__echo", "arguments": {}}).status_code == 400
    meta = activity_by_id(client, entry["id"])["metadata"]
    assert "undoing" not in meta and "undone_at" not in meta

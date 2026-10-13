"""The daily briefing, and the read-only "ask the agent" step it is built from."""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_chatbot import FIXTURE, ScriptedLLM


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        echo = c.post("/api/mcp/servers", json={"name": "Brief Echo", "transport": "stdio", "command": sys.executable,
                                                 "args": [FIXTURE], "tool_policies": {"echo": "ask"}}).json()
        c.slug = echo["slug"]
        yield c
        c.delete(f"/api/mcp/servers/{echo['id']}")


@pytest.fixture
def llm(monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    fake = ScriptedLLM(lambda m, t: {"content": "## Calendar\n- 10:00 Standup", "tool_calls": []})
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "m"}), {}))
    return fake


def test_ask_agent_runs_read_only_and_returns_the_answer(client, llm):
    from app.tools import get_tool_registry

    out = client.portal.call(get_tool_registry().get_tool("nexus__ask_agent").execute,
                             {"prompt": "echo and list items from my apps"})
    assert out["text"] == "## Calendar\n- 10:00 Standup"
    offered = next(c for c in llm.calls if c["kind"] == "tools")["tools"]
    assert f"{client.slug}__list_items" in offered  # reads are fine
    assert f"{client.slug}__echo" not in offered  # needs an approval nobody is there to give
    assert "nexus_ask_user" not in offered and "nexus__ask_agent" not in offered


def test_chat_never_offers_ask_agent(client, llm):
    sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
    client.post("/api/agent/run", json={"message": "ask the agent to list items", "session_id": sid})
    assert all("nexus__ask_agent" not in c.get("tools", []) for c in llm.calls)


def test_setting_up_the_briefing_makes_one_workflow(client):
    saved = client.put("/api/briefing", json={"enabled": True, "time": "07:30", "weekdays_only": True,
                                              "sections": ["calendar", "email"], "notes": "Skip newsletters"}).json()
    assert saved["enabled"] is True and saved["next_run_at"]
    workflow = client.get(f"/api/workflows/{saved['workflow_id']}").json()
    trigger = workflow["trigger_config"]
    assert trigger["type"] == "recurrence" and trigger["at"] == "07:30" and trigger["weekdays"] == ["mon", "tue", "wed", "thu", "fri"]
    prompt = next(n for n in workflow["nodes"] if n["config"].get("tool") == "nexus__ask_agent")["config"]["parameters"]["prompt"]
    assert "calendar" in prompt.lower() and "unread email" in prompt.lower() and "Skip newsletters" in prompt
    assert "feeds" not in prompt.lower()
    assert any(n["config"].get("tool") == "nexus__notify" for n in workflow["nodes"])

    again = client.put("/api/briefing", json={"enabled": True, "time": "09:00", "weekdays_only": False,
                                              "sections": ["feeds"], "notes": ""}).json()
    assert again["workflow_id"] == saved["workflow_id"]  # updated, not duplicated
    assert client.get(f"/api/workflows/{saved['workflow_id']}").json()["trigger_config"]["frequency"] == "day"

    off = client.put("/api/briefing", json={**again, "enabled": False}).json()
    assert off["enabled"] is False and client.get(f"/api/workflows/{saved['workflow_id']}").json()["isActive"] is False
    assert client.get("/api/briefing").json()["sections"] == ["feeds"]
    client.delete(f"/api/workflows/{saved['workflow_id']}")


def test_send_one_now(client, llm, monkeypatch):
    from app.integrations import telegram

    sent = []

    async def phone(title, message=""):
        sent.append((title, message))

    monkeypatch.setattr(telegram, "notify_all", phone)
    client.put("/api/briefing", json={"enabled": False, "time": "08:00", "weekdays_only": True, "sections": ["calendar"], "notes": ""})
    result = client.post("/api/briefing/send-now").json()
    assert result["text"] == "## Calendar\n- 10:00 Standup"
    assert sent and sent[0] == ("Your daily briefing", "## Calendar\n- 10:00 Standup")

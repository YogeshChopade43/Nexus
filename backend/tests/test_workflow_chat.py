"""Managing existing workflows from chat: list them, pause/resume, change the schedule, delete."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.knowledge import ChangeWorkflow, ListWorkflows
from app.main import app
from tests.test_chatbot import ScriptedLLM, new_session  # noqa: F401
from app.llm.metering import Metered

REMINDER = {"name": "Medicine reminder", "description": "Every day at 13:00 remind me to take my medicines",
            "isActive": True, "edges": [{"source": "t", "target": "n"}],
            "nodes": [{"id": "t", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day",
                                                                 "at": "13:00", "timezone": "UTC"}},
                      {"id": "n", "type": "action", "config": {"tool": "nexus__notify",
                                                               "parameters": {"title": "Take your medicines"}}}]}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def workflow(client):
    created = client.post("/api/workflows", json=REMINDER).json()
    yield created
    client.delete(f"/api/workflows/{created['id']}")


def run(coro):
    return asyncio.run(coro)


def test_list_shows_each_workflow_with_its_state_and_next_run(client, workflow):
    text = run(ListWorkflows().execute({}))["text"]
    line = next(line for line in text.splitlines() if "Medicine reminder" in line)
    assert f"#{workflow['id']}" in line and "(active)" in line and "next run" in line.lower()


def test_pause_and_resume_by_name(client, workflow):
    run(ChangeWorkflow().execute({"workflow": "medicine reminder", "action": "pause"}))
    assert client.get(f"/api/workflows/{workflow['id']}").json()["isActive"] is False
    run(ChangeWorkflow().execute({"workflow": str(workflow["id"]), "action": "resume"}))
    assert client.get(f"/api/workflows/{workflow['id']}").json()["isActive"] is True


def test_edit_redrafts_from_the_current_workflow(client, workflow, monkeypatch):
    from app.workflows import drafting
    seen = {}

    async def draft(description, current=None):
        seen.update(description=description, current=current)
        nodes = [dict(n) for n in current["nodes"]]
        nodes[0] = {**nodes[0], "config": {**nodes[0]["config"], "at": "15:00"}}
        return {"name": current["name"], "description": "Every day at 15:00", "nodes": nodes, "edges": current["edges"]}

    monkeypatch.setattr(drafting, "draft_workflow", draft)
    result = run(ChangeWorkflow().execute({"workflow": "Medicine", "action": "edit", "change": "move it to 3 pm"}))
    assert seen["description"] == "move it to 3 pm" and seen["current"]["name"] == "Medicine reminder"
    updated = client.get(f"/api/workflows/{workflow['id']}").json()
    assert updated["trigger_config"]["at"] == "15:00" and updated["version"] == 2
    assert "Medicine reminder" in result["text"]


def test_delete_and_unknown_names(client, workflow):
    with pytest.raises(ValueError, match="No workflow"):
        run(ChangeWorkflow().execute({"workflow": "does not exist", "action": "pause"}))
    run(ChangeWorkflow().execute({"workflow": workflow["name"], "action": "delete"}))
    assert client.get(f"/api/workflows/{workflow['id']}").status_code == 404


def test_edit_needs_a_change(client, workflow):
    with pytest.raises(ValueError, match="change"):
        run(ChangeWorkflow().execute({"workflow": workflow["name"], "action": "edit"}))


def test_chat_offers_workflow_tools_for_reminders_and_follow_ups(client, monkeypatch):
    import app.api.routes.agent as agent_route
    llm = ScriptedLLM(lambda m, t: {"content": "ok", "tool_calls": []})
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(llm, None, {"model": "fake-model"}), {}))
    offered = lambda: next(c for c in llm.calls if c["kind"] == "tools")["tools"]  # noqa: E731

    sid = new_session(client)
    client.post("/api/agent/run", json={"message": "what reminders do I have?", "session_id": sid})
    assert {"nexus__list_workflows", "nexus__change_workflow"} <= set(offered())
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "pause the second one", "session_id": sid})  # follows the topic
    assert "nexus__change_workflow" in offered()
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "what is the capital of France", "session_id": new_session(client)})
    assert not any(c["kind"] == "tools" and "nexus__list_workflows" in c["tools"] for c in llm.calls)

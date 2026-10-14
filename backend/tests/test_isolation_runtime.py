"""Two accounts at runtime: Ana's connected apps are her tools only. Bo's agent never sees them, and Bo's workflows
can't run them (not even by naming them), so nothing ever runs on Ana's credentials for Bo."""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from app.auth.owner import as_user
from app.main import app
from app.mcp import server_states
from tests.test_chatbot import FIXTURE, ScriptedLLM


@pytest.fixture(scope="module")
def ana():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def bo():
    with TestClient(app, user="bo@example.com") as c:
        yield c


@pytest.fixture(scope="module")
def anas_app(ana):
    server = ana.post("/api/mcp/servers", json={"name": "Ana Echo", "transport": "stdio", "command": sys.executable,
                                                 "args": [FIXTURE]}).json()
    assert "slug" in server, server
    for _ in range(100):
        if ana.get(f"/api/mcp/servers/{server['id']}").json().get("status") == "connected":
            break
        import time

        time.sleep(0.1)
    yield server
    ana.delete(f"/api/mcp/servers/{server['id']}")


def bo_id() -> int:
    return store._row("email = ?", "bo@example.com")["id"]


def test_app_states_are_per_person(ana, bo, anas_app):
    assert server_states()[anas_app["slug"]]["available"] is True  # tests act as Ana (the test account)
    with as_user(bo_id()):
        assert anas_app["slug"] not in server_states()
        assert "nexus" in server_states()  # Nexus's own tools are everyone's


def test_bos_agent_is_never_offered_anas_tools(bo, anas_app, monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    fake = ScriptedLLM()
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "m"}), {}))
    bo.post("/api/agent/run", json={"message": "echo the text hello with Ana Echo"})
    offered = {name for call in fake.calls if call["kind"] == "tools" for name in call["tools"]}
    assert not any(name.startswith(anas_app["slug"] + "__") for name in offered)


def test_bos_workflow_cannot_run_anas_tool_by_naming_it(bo, anas_app):
    wf = bo.post("/api/workflows/", json={"name": "Borrow Ana's app", "nodes": [
        {"id": "steal", "type": "action", "name": "Use Ana's echo",
         "config": {"tool": f"{anas_app['slug']}__echo", "parameters": {"text": "hi"}}}], "edges": []}).json()
    run = bo.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "failed"
    assert "echo: hi" not in str(run)  # Ana's server never ran it


def test_ana_still_uses_her_own(ana, anas_app):
    wf = ana.post("/api/workflows/", json={"name": "My echo", "nodes": [
        {"id": "echo", "type": "action", "name": "Echo",
         "config": {"tool": f"{anas_app['slug']}__echo", "parameters": {"text": "hi"}}}], "edges": []}).json()
    run = ana.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "completed", run.get("error")


def poll_workflow(client, tool: str) -> dict:
    return client.post("/api/workflows/", json={"name": f"Watch {tool}", "isActive": True,
        "trigger_config": {"type": "poll", "tool": tool, "interval_minutes": 5, "items_path": "items"},
        "nodes": [{"id": "say", "type": "transform", "name": "Say", "config": {"template": "new"}}], "edges": []}).json()


def test_polling_runs_as_the_workflows_owner(ana, bo, anas_app):
    """A scheduled check has no one signed in: Bo's watcher naming Ana's tool must not read Ana's app."""
    from app.auth.context import current_user
    from app.workflows import polling

    bos = poll_workflow(bo, f"{anas_app['slug']}__list_items")
    anas = poll_workflow(ana, f"{anas_app['slug']}__list_items")
    token = current_user.set(None)  # like the scheduler
    try:
        bos_check = bo.portal.call(polling.poll_once, bos["id"])
        anas_check = ana.portal.call(polling.poll_once, anas["id"])
    finally:
        current_user.reset(token)
    assert bos_check.get("error") and not bos_check.get("new")
    assert not anas_check.get("error"), anas_check


def test_app_events_only_start_the_apps_owners_workflows(ana, bo, anas_app):
    from app.triggers.engine import matching_workflows
    from app.triggers.models import TriggerEvent

    event_trigger = {"type": "app_event", "app_id": anas_app["slug"], "event": "item.created"}
    bos = bo.post("/api/workflows/", json={"name": "Bo listens to Ana's app", "isActive": True, "trigger_config": event_trigger,
                                           "nodes": [], "edges": []}).json()
    anas = ana.post("/api/workflows/", json={"name": "Ana listens to her app", "isActive": True, "trigger_config": event_trigger,
                                             "nodes": [], "edges": []}).json()
    matched = {m.workflow_id for m in matching_workflows(TriggerEvent(trigger_type="app_event", app_id=anas_app["slug"],
                                                                      event_name="item.created"))}
    assert anas["id"] in matched and bos["id"] not in matched


def test_instance_wide_powers_are_the_admins_only(bo):
    """With many accounts: the whole-database backup, instance API settings and programs run on the server itself."""
    assert bo.get("/api/settings/backup").status_code == 403
    assert bo.patch("/api/settings/api", json={"timeout": 5}).status_code == 403
    local = bo.post("/api/mcp/servers", json={"name": "Bo's script", "transport": "stdio", "command": "cmd", "args": []})
    assert local.status_code == 403

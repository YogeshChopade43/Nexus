"""Run-once workflows: run a single time, on a date, or if you go quiet (with warnings first), then stop."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.routes import run_once
from app.main import app
from tests.test_chatbot import ScriptedLLM

DAY = timedelta(days=1)
NOW = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)  # ahead of the real minute-by-minute check


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def world(client, monkeypatch):
    """A clock we move by hand, and a record of what was sent and run."""
    sent, ran = [], []

    async def notify_all(title, message=""):
        sent.append(title)

    async def run(workflow_id, *args, **kwargs):
        ran.append(workflow_id)

    monkeypatch.setattr("app.integrations.telegram.notify_all", notify_all)
    monkeypatch.setattr(run_once, "_run_scheduled", run)
    tick = lambda at: client.portal.call(run_once.tick, at)  # noqa: E731
    made = []
    yield client, tick, sent, ran, made
    for item in made:
        client.delete(f"/api/run-once/{item}")


def make(client, made, steps=True, **body):
    created = client.post("/api/run-once", json=body)
    assert created.status_code == 200, created.text
    item = created.json()
    made.append(item["id"])
    if steps:  # something to run (a run-once starts with none)
        wf = client.get(f"/api/workflows/{item['workflowId']}").json()
        client.patch(f"/api/workflows/{item['workflowId']}", json={
            "nodes": [*wf["nodes"], {"id": "say", "type": "transform", "name": "Say", "config": {"template": "hi"}}],
            "edges": [{"id": "e1", "source": wf["nodes"][0]["id"], "target": "say"}]})
    return item


def items(client):
    return {i["id"]: i for i in client.get("/api/run-once").json()["items"]}


def test_a_run_once_gets_its_own_workflow_to_fill_in(world):
    client, *_, made = world
    item = make(client, made, name="Birthday message to Mom", kind="at", at=iso(NOW + 30 * DAY))
    assert item["status"] == "scheduled" and item["runsAt"] == iso(NOW + 30 * DAY)
    wf = client.get(f"/api/workflows/{item['workflowId']}").json()
    assert wf["name"] == "Birthday message to Mom" and wf["folder"] == "Run once" and wf["trigger"] == "manual"
    assert client.post("/api/run-once", json={"name": "x", "kind": "quiet", "days": 1}).status_code == 422  # too short
    assert client.post("/api/run-once", json={"name": "x", "kind": "at"}).status_code == 422  # when?


def test_on_a_date_it_runs_once_at_that_time(world):
    client, tick, sent, ran, made = world
    item = make(client, made, name="Send the report", kind="at", at=iso(NOW + DAY))
    tick(NOW + DAY - timedelta(minutes=1))
    assert ran == []
    tick(NOW + DAY + timedelta(minutes=1))
    assert ran == [item["workflowId"]] and items(client)[item["id"]]["status"] == "done"
    tick(NOW + 2 * DAY)
    assert ran == [item["workflowId"]]  # once only


def test_a_date_missed_by_long_is_reported_not_run_late(world):
    client, tick, sent, ran, made = world
    item = make(client, made, name="Birthday wishes", kind="at", at=iso(NOW + DAY))
    tick(NOW + 4 * DAY)  # Nexus was off on the day
    assert ran == [] and items(client)[item["id"]]["status"] == "missed"
    assert any("missed" in title.lower() for title in sent)


def test_if_i_go_quiet_it_warns_first_then_runs_once(world):
    client, tick, sent, ran, made = world
    start = datetime.fromisoformat(client.post("/api/run-once/check-in").json()["lastCheckIn"].replace("Z", "+00:00"))
    item = make(client, made, name="Share documents with family", kind="quiet", days=14)
    tick(start + 10 * DAY)
    assert sent == [] and ran == []
    tick(start + 11 * DAY + timedelta(minutes=1))
    assert len(sent) == 1 and "Share documents with family" in sent[0]  # 3 days early, by name
    tick(start + 11 * DAY + timedelta(hours=3))
    assert len(sent) == 1  # not every few minutes
    tick(start + 12 * DAY + timedelta(hours=1))
    assert len(sent) == 2  # but daily
    tick(start + 14 * DAY + timedelta(hours=1))
    assert ran == [item["workflowId"]] and items(client)[item["id"]]["status"] == "done"


def test_after_weeks_off_it_warns_and_waits_instead_of_firing(world):
    client, tick, sent, ran, made = world
    start = datetime.fromisoformat(client.post("/api/run-once/check-in").json()["lastCheckIn"].replace("Z", "+00:00"))
    item = make(client, made, name="Safety net", kind="quiet", days=7)
    tick(start + 30 * DAY)
    assert ran == [] and len(sent) == 1
    tick(start + 32 * DAY + timedelta(hours=1))
    assert ran == [item["workflowId"]]


def test_checking_in_stops_the_warnings(world):
    client, tick, sent, ran, made = world
    start = datetime.fromisoformat(client.post("/api/run-once/check-in").json()["lastCheckIn"].replace("Z", "+00:00"))
    item = make(client, made, name="Quiet check", kind="quiet", days=7)
    tick(start + 5 * DAY)
    assert items(client)[item["id"]]["status"] == "warning"
    client.post("/api/run-once/check-in")
    assert items(client)[item["id"]]["status"] == "armed"


def test_chatting_counts_as_checking_in(world, monkeypatch):
    client, *_ = world
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(ScriptedLLM(), None, {"model": "m"}), {}))
    before = client.get("/api/run-once").json()["lastCheckIn"] or ""
    client.post("/api/agent/run", json={"message": "hi"})
    assert client.get("/api/run-once").json()["lastCheckIn"] > before


def test_pause_change_and_delete(world):
    client, tick, sent, ran, made = world
    item = make(client, made, name="Later", kind="at", at=iso(NOW + DAY))
    paused = client.patch(f"/api/run-once/{item['id']}", json={"enabled": False}).json()
    assert paused["status"] == "off"
    tick(NOW + DAY + timedelta(minutes=1))
    assert ran == []
    moved = client.patch(f"/api/run-once/{item['id']}", json={"enabled": True, "at": iso(NOW + 2 * DAY)}).json()
    assert moved["status"] == "scheduled" and moved["runsAt"] == iso(NOW + 2 * DAY)
    assert client.delete(f"/api/run-once/{item['id']}").status_code == 204
    made.remove(item["id"])
    assert client.get(f"/api/workflows/{item['workflowId']}").status_code == 404  # its workflow goes too


def test_running_it_by_hand_needs_a_confirmation(world):
    client, *_, made = world
    item = make(client, made, name="Handle with care", kind="quiet", days=14)
    refused = client.post(f"/api/workflows/{item['workflowId']}/run", json={})
    assert refused.status_code == 409 and "run once" in refused.json()["detail"].lower()
    assert client.post(f"/api/workflows/{item['workflowId']}/run", json={"confirm": True}).status_code == 200


def test_when_it_fires_your_steps_run_and_only_they_message_you(client, monkeypatch):
    """No stand-in for the run: its workflow executes. Nexus adds no message of its own (that went to Telegram)."""
    sent = []

    async def notify_all(title, message=""):
        sent.append(title)

    monkeypatch.setattr("app.integrations.telegram.notify_all", notify_all)
    item = client.post("/api/run-once", json={"name": "Real one", "kind": "at", "at": iso(NOW + DAY)}).json()
    assert item["steps"] == 0  # starts empty: no placeholder step
    wf = client.get(f"/api/workflows/{item['workflowId']}").json()
    assert [n["type"] for n in wf["nodes"]] == ["trigger"]
    client.patch(f"/api/workflows/{item['workflowId']}", json={"isActive": False, "nodes": [  # off by hand: still runs
        *wf["nodes"], {"id": "wish", "type": "action", "name": "Wish", "config": {
            "tool": "nexus__notify", "parameters": {"title": "Happy Birthday"}}}],
        "edges": [{"id": "e1", "source": wf["nodes"][0]["id"], "target": "wish"}]})
    try:
        assert client.portal.call(run_once.tick, NOW + DAY + timedelta(minutes=1)) == ["ran"]
        runs = client.get(f"/api/workflows/{item['workflowId']}/runs").json()
        listed = runs["runs"] if isinstance(runs, dict) else runs
        assert listed and listed[0]["status"] == "completed", listed[:1]
        assert sent == ["Happy Birthday"]  # your step, and nothing else on your phone
    finally:
        client.delete(f"/api/run-once/{item['id']}")


def test_with_no_steps_it_only_notes_in_the_bell(world):
    client, tick, sent, ran, made = world
    item = make(client, made, steps=False, name="Empty one", kind="at", at=iso(NOW + DAY))
    tick(NOW + DAY + timedelta(minutes=1))
    assert ran == [] and sent == []  # nothing to run, nothing sent to your phone
    assert items(client)[item["id"]]["status"] == "done"
    bell = client.get("/api/activity/notifications").json()
    assert any("Empty one" in n["title"] for n in bell["items"])


def test_the_old_placeholder_step_is_taken_out(client):
    """Run-onces made before this change had a "Note that it ran" step that messaged Telegram."""
    item = client.post("/api/run-once", json={"name": "Older one", "kind": "quiet", "days": 14}).json()
    wf = client.get(f"/api/workflows/{item['workflowId']}").json()
    placeholder = {"id": "tell", "type": "action", "name": "Note that it ran", "config": {
        "tool": "nexus__notify", "parameters": {"title": "“Older one” ran", "message": "Your run-once workflow ran."}}}
    mine = {"id": "mine", "type": "action", "name": "Mine", "config": {"tool": "nexus__notify", "parameters": {"title": "Hi"}}}
    trigger = wf["nodes"][0]["id"]
    client.patch(f"/api/workflows/{item['workflowId']}", json={"nodes": [*wf["nodes"], placeholder, mine], "edges": [
        {"id": "a", "source": trigger, "target": "tell"}, {"id": "b", "source": "tell", "target": "mine"}]})
    try:
        listed = next(i for i in client.get("/api/run-once").json()["items"] if i["id"] == item["id"])
        assert listed["steps"] == 1
        after = client.get(f"/api/workflows/{item['workflowId']}").json()
        assert [n["id"] for n in after["nodes"]] == [trigger, "mine"]
        assert after["edges"] == [{"id": "b", "source": trigger, "target": "mine"}]  # still connected
    finally:
        client.delete(f"/api/run-once/{item['id']}")


def test_an_existing_digital_will_becomes_a_quiet_run_once(client):
    from app.api.routes.settings import update_user_settings

    wf = client.post("/api/workflows", json={"name": "Digital will", "nodes": [], "edges": [], "folder": "Digital will"}).json()
    update_user_settings({"will": {"enabled": True, "days": 21, "workflowId": wf["id"], "lastCheckIn": iso(NOW - DAY)}})
    try:
        adopted = next(i for i in client.get("/api/run-once").json()["items"] if i["workflowId"] == wf["id"])
        assert adopted["kind"] == "quiet" and adopted["days"] == 21 and adopted["status"] == "armed"
        assert client.get(f"/api/workflows/{wf['id']}").json()["folder"] == "Run once"
        assert len([i for i in client.get("/api/run-once").json()["items"] if i["workflowId"] == wf["id"]]) == 1  # once
    finally:
        client.delete(f"/api/run-once/{adopted['id']}")


def test_steps_can_be_given_when_it_is_made(world):
    client, *_, made = world
    steps = [{"id": "wish", "type": "action", "name": "Wish Mom", "config": {"tool": "nexus__notify", "parameters": {"title": "Happy Birthday"}}},
             {"id": "log", "type": "transform", "name": "Note", "config": {"template": "sent"}}]
    item = make(client, made, steps=False, name="Birthday", kind="at", at=iso(NOW + DAY), nodes=steps)
    assert item["steps"] == 2
    wf = client.get(f"/api/workflows/{item['workflowId']}").json()
    trigger = wf["nodes"][0]["id"]
    assert [n["id"] for n in wf["nodes"]] == [trigger, "wish", "log"]
    assert [(e["source"], e["target"]) for e in wf["edges"]] == [(trigger, "wish"), ("wish", "log")]  # one after another

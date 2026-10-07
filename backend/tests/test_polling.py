from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workflows import polling, scheduler

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
FEED = Path(tempfile.mkdtemp(prefix="nexus-feed-")) / "feed.json"


def write_feed(items):
    FEED.write_text(json.dumps(items), encoding="utf-8")


@pytest.fixture(scope="module")
def client():
    write_feed([])
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={
            "name": "Feed", "transport": "stdio", "command": sys.executable,
            "args": [FIXTURE], "env": {"FEED_FILE": str(FEED)},
        })
        assert r.json()["status"] == "connected", r.json()
        c.feed_server_id = r.json()["id"]
        yield c


def make_workflow(client, **trigger):
    config = {"trigger_type": "poll", "tool": "feed__list_feed", "interval_minutes": 5, **trigger}
    r = client.post("/api/workflows", json={
        "name": "poller", "isActive": True,
        "nodes": [{"id": "t", "type": "trigger", "config": config},
                  {"id": "x", "type": "transform", "config": {"template": "{{ trigger.item.title }}"}}],
        "edges": [{"source": "t", "target": "x"}],
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def poll(client, workflow_id):
    return client.portal.call(polling.poll_once, workflow_id)


def runs(client, workflow_id):
    return client.get(f"/api/workflows/{workflow_id}/runs").json()["runs"]


def test_baseline_starts_nothing(client):
    write_feed([{"id": 1}, {"id": 2}])
    wf = make_workflow(client)
    assert poll(client, wf)["started"] == 0
    assert runs(client, wf) == []


def test_new_item_runs_once(client):
    write_feed([{"id": 1}, {"id": 2}])
    wf = make_workflow(client)
    poll(client, wf)
    write_feed([{"id": 1}, {"id": 2}, {"id": 3, "title": "new"}])
    assert poll(client, wf)["started"] == 1
    assert runs(client, wf)[0]["events"][0]["output"]["value"] == "new"
    assert poll(client, wf)["started"] == 0


def test_identical_items_without_id(client):
    write_feed([])
    wf = make_workflow(client)
    poll(client, wf)
    write_feed([{"t": "a"}, {"t": "a"}])
    assert poll(client, wf)["started"] == 1


def test_cap_25(client):
    write_feed([])
    wf = make_workflow(client)
    poll(client, wf)
    write_feed([{"id": n} for n in range(30)])
    assert poll(client, wf)["started"] == 25
    assert "25" in polling.get_status(wf)["last_error"]
    assert poll(client, wf)["started"] == 0  # the 5 extra items were recorded as seen
    assert polling.get_status(wf)["last_error"] is None  # status reflects the latest check


def test_tool_error_records_status(client):
    wf = make_workflow(client, tool="feed__fail")
    result = poll(client, wf)
    assert result["error"] and result["started"] == 0
    assert runs(client, wf) == []
    status = client.get(f"/api/workflows/{wf}").json()["trigger_status"]
    assert status["last_error"]


def test_items_path(client):
    write_feed([{"id": 1}])
    wf = make_workflow(client, items_path="items")
    assert poll(client, wf)["error"] is None
    bad = make_workflow(client, items_path="nope")
    assert "Could not find a list" in poll(client, bad)["error"]


def test_disconnected_server(client):
    write_feed([{"id": 1}])
    wf = make_workflow(client)
    poll(client, wf)
    client.patch(f"/api/mcp/servers/{client.feed_server_id}", json={"enabled": False})
    try:
        write_feed([{"id": 1}, {"id": 2}])
        result = poll(client, wf)
        assert "not connected" in result["error"] and result["started"] == 0
    finally:
        assert client.patch(f"/api/mcp/servers/{client.feed_server_id}", json={"enabled": True}).json()["status"] == "connected"
    assert poll(client, wf)["started"] == 1  # item 2 was not marked seen while disconnected


def test_change_resets_and_type_change_removes_job(client):
    write_feed([{"id": 1}])
    wf = make_workflow(client)
    poll(client, wf)
    assert scheduler.next_run_time(wf) is not None

    nodes = client.get(f"/api/workflows/{wf}").json()["nodes"]
    nodes[0]["config"]["parameters"] = {"x": 1}
    client.patch(f"/api/workflows/{wf}", json={"nodes": nodes})
    write_feed([{"id": 1}, {"id": 2}])
    assert poll(client, wf)["started"] == 0  # new baseline

    nodes[0]["config"] = {"trigger_type": "manual"}
    client.patch(f"/api/workflows/{wf}", json={"nodes": nodes})
    assert scheduler.next_run_time(wf) is None
    assert polling.get_status(wf) is None


def test_manual_run_uses_latest_item(client):
    write_feed([{"id": 5, "title": "latest"}, {"id": 4, "title": "older"}])
    wf = make_workflow(client)
    run = client.post(f"/api/workflows/{wf}/run", json={}).json()
    assert run["status"] == "completed", run
    assert run["events"][0]["output"]["value"] == "latest"

    write_feed([])
    r = client.post(f"/api/workflows/{wf}/run", json={})
    assert r.status_code == 400 and "no items" in r.json()["detail"]

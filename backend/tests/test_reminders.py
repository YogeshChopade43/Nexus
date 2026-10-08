"""Reminders: the "notify me" workflow step, and timezones that default to the user's own."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes.settings import normalize_timezone
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_notify_step_shows_in_the_bell(client):
    nodes = [{"id": "t", "type": "trigger", "config": {"trigger_type": "manual"}},
             {"id": "n", "type": "action", "config": {"tool": "nexus__notify",
                                                      "parameters": {"title": "Take your medicines", "message": "2 tablets"}}}]
    wf = client.post("/api/workflows", json={"name": "pill reminder", "nodes": nodes,
                                             "edges": [{"source": "t", "target": "n"}], "isActive": True})
    assert wf.status_code == 200, wf.text
    run = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"input_data": {}}).json()
    assert run["status"] == "completed", run
    items = client.get("/api/activity/notifications").json()["items"]
    assert any(i["type"] == "reminder" and i["title"] == "Take your medicines" and i["description"] == "2 tablets"
               for i in items)


def test_settings_accept_only_real_timezones(client):
    assert client.patch("/api/settings/user", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.patch("/api/settings/user", json={"timezone": "Asia/Kolkata"}).json()["timezone"] == "Asia/Kolkata"
    # Values typed before the dropdown existed are read as the matching zone.
    assert normalize_timezone("Kolkata") == "Asia/Kolkata"
    assert normalize_timezone("Nowhere") == "UTC"


def test_trigger_without_timezone_uses_the_settings_timezone(client):
    client.patch("/api/settings/user", json={"timezone": "Asia/Kolkata"})
    nodes = [{"id": "t", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day",
                                                       "at": "23:57", "timezone": None}}]
    wf = client.post("/api/workflows", json={"name": "tz default", "nodes": nodes, "edges": [], "isActive": False}).json()
    assert client.get(f"/api/workflows/{wf['id']}").json()["trigger_config"]["timezone"] == "Asia/Kolkata"
    preview = client.post("/api/workflows/recurrence/preview", json={"frequency": "day", "at": "23:57", "timezone": None})
    assert preview.json()["next_runs"][0].endswith("+05:30")

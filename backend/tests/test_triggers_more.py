"""Section 3: richer schedules, precise polling, and Slack/Notion app events."""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.triggers.models import TriggerConfig
from app.workflows import polling, recurrence

UTC = ZoneInfo("UTC")
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


def cfg(**kwargs) -> TriggerConfig:
    return TriggerConfig(type="recurrence", **kwargs)


# ---- schedules ---------------------------------------------------------------------

def test_null_settings_fall_back_to_defaults():
    """AI drafts and older clients send null for unset fields, e.g. "timezone": null."""
    config = cfg(frequency="day", timezone=None, interval=None, at=None, weekdays=None)
    assert (config.timezone, config.interval, config.at, config.weekdays) == ("UTC", 1, "00:00", [])


def test_every_two_weeks_on_monday():
    runs = recurrence.next_runs(cfg(frequency="week", interval=2, weekdays=["mon"], at="10:00", anchor="2026-10-05"), now=NOW)
    assert [r.date().isoformat() for r in runs] == ["2026-10-19", "2026-11-02", "2026-11-16"]


def test_every_two_months():
    runs = recurrence.next_runs(cfg(frequency="month", interval=2, month_day=15, at="09:00", anchor="2026-10-01"), now=NOW)
    assert [r.date().isoformat() for r in runs] == ["2026-10-15", "2026-12-15", "2027-02-15"]


def test_last_day_of_month():
    runs = recurrence.next_runs(cfg(frequency="month", month_day=-1, at="18:00"), now=NOW)
    assert [r.date().isoformat() for r in runs] == ["2026-10-31", "2026-11-30", "2026-12-31"]


def test_every_n_days_keeps_its_phase():
    config = cfg(frequency="day", interval=2, at="09:00", anchor="2026-10-01")
    first = recurrence.next_runs(config, now=NOW)
    later = recurrence.next_runs(config, now=NOW + timedelta(hours=12))  # e.g. after a restart
    assert [r.date().isoformat() for r in first] == ["2026-10-07", "2026-10-09", "2026-10-11"]
    assert later[0].date().isoformat() == "2026-10-09"


def test_bad_month_day_rejected():
    with pytest.raises(ValueError):
        recurrence.validate(cfg(frequency="month", month_day=0))


# ---- precise polling -------------------------------------------------------------------

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
FEED = Path(tempfile.mkdtemp(prefix="nexus-feed2-")) / "feed.json"


def write_feed(items):
    FEED.write_text(json.dumps(items), encoding="utf-8")


@pytest.fixture(scope="module")
def client():
    write_feed([])
    from app.core.database import get_connection

    conn = get_connection()
    try:  # instance-wide webhooks (secrets in the environment) start the admin's workflows: test as the admin
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'tester@example.com'")
        conn.commit()
    finally:
        conn.close()
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={"name": "Feed2", "transport": "stdio", "command": sys.executable,
                                             "args": [FIXTURE], "env": {"FEED_FILE": str(FEED)}})
        assert r.json()["status"] == "connected", r.json()
        yield c


def poll_workflow(client, **trigger):
    config = {"trigger_type": "poll", "tool": "feed2__list_feed", "interval_minutes": 5, **trigger}
    r = client.post("/api/workflows", json={"name": "p", "isActive": True, "nodes": [
        {"id": "t", "type": "trigger", "config": config},
        {"id": "x", "type": "transform", "config": {"template": "{{ trigger.item.id }}"}},
    ], "edges": [{"source": "t", "target": "x"}]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def poll(client, wf):
    return client.portal.call(polling.poll_once, wf)["started"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_new_or_updated_mode(client):
    write_feed([{"id": 1, "updated_at": "v1"}])
    new_only = poll_workflow(client)
    updates = poll_workflow(client, poll_mode="new_or_updated")
    poll(client, new_only), poll(client, updates)
    write_feed([{"id": 1, "updated_at": "v2"}])
    assert poll(client, new_only) == 0
    assert poll(client, updates) == 1


def test_old_item_appearing_later_is_ignored(client):
    write_feed([{"id": 1, "created_time": iso(datetime.now(timezone.utc) - timedelta(days=30))}])
    wf = poll_workflow(client)
    poll(client, wf)
    write_feed([
        {"id": 1, "created_time": iso(datetime.now(timezone.utc) - timedelta(days=30))},
        {"id": 2, "created_time": iso(datetime.now(timezone.utc) - timedelta(days=10))},  # old, just edited
        {"id": 3, "created_time": iso(datetime.now(timezone.utc) + timedelta(seconds=1))},  # really new
    ])
    assert poll(client, wf) == 1
    runs = client.get(f"/api/workflows/{wf}/runs").json()["runs"]
    assert runs[0]["events"][0]["output"]["value"] == 3


def test_item_filter(client):
    write_feed([])
    wf = poll_workflow(client, filter_field="item.title", filter_operator="contains", filter_value="urgent")
    poll(client, wf)
    write_feed([{"id": 5, "title": "urgent fix"}, {"id": 6, "title": "chore"}])
    assert poll(client, wf) == 1
    write_feed([{"id": 5, "title": "urgent fix"}, {"id": 6, "title": "now urgent too"}])
    assert poll(client, wf) == 0  # item 6 was already seen; new-only mode ignores edits


# ---- Slack & Notion app events ------------------------------------------------------------

def app_event_workflow(client, app_id, event):
    r = client.post("/api/workflows", json={"name": f"{app_id} events", "isActive": True, "nodes": [
        {"id": "t", "type": "trigger", "config": {"trigger_type": "app_event", "app_id": app_id, "event": event}},
        {"id": "x", "type": "transform", "config": {"template": "got {{ trigger.event }}"}},
    ], "edges": [{"source": "t", "target": "x"}]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait_for_run(client, wf):
    for _ in range(50):
        runs = client.get(f"/api/workflows/{wf}/runs").json()["runs"]
        if runs and runs[0]["status"] != "running":
            return runs[0]
        time.sleep(0.1)
    raise AssertionError("no run")


def slack_headers(secret: str, body: bytes, ts: int | None = None) -> dict:
    ts = ts or int(time.time())
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return {"x-slack-request-timestamp": str(ts), "x-slack-signature": sig, "content-type": "application/json"}


def test_slack_events(client, monkeypatch):
    monkeypatch.setenv("NEXUS_SLACK_SIGNING_SECRET", "slack-secret")
    challenge = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    r = client.post("/api/webhooks/apps/slack", content=challenge, headers=slack_headers("slack-secret", challenge))
    assert r.status_code == 200 and r.json() == {"challenge": "abc123"}

    wf = app_event_workflow(client, "slack", "slack.app_mention")
    body = json.dumps({"type": "event_callback", "event": {"type": "app_mention", "text": "hi"}}).encode()
    assert client.post("/api/webhooks/apps/slack", content=body, headers=slack_headers("wrong", body)).status_code == 403
    stale = slack_headers("slack-secret", body, ts=int(time.time()) - 3600)
    assert client.post("/api/webhooks/apps/slack", content=body, headers=stale).status_code == 403
    r = client.post("/api/webhooks/apps/slack", content=body, headers=slack_headers("slack-secret", body))
    assert r.status_code == 202 and r.json()["event"] == "slack.app_mention" and wf in r.json()["workflows"]
    assert wait_for_run(client, wf)["events"][0]["output"]["value"] == "got slack.app_mention"


def test_notion_events(client, monkeypatch):
    monkeypatch.setenv("NEXUS_NOTION_WEBHOOK_TOKEN", "notion-token")
    r = client.post("/api/webhooks/apps/notion", json={"verification_token": "secret_from_notion"})
    assert r.status_code == 200 and r.json()["verification_received"] is True

    wf = app_event_workflow(client, "notion", "notion.page.created")
    body = json.dumps({"type": "page.created", "entity": {"id": "p1", "type": "page"}}).encode()
    sig = "sha256=" + hmac.new(b"notion-token", body, hashlib.sha256).hexdigest()
    bad = client.post("/api/webhooks/apps/notion", content=body, headers={"x-notion-signature": "sha256=bad", "content-type": "application/json"})
    assert bad.status_code == 403
    r = client.post("/api/webhooks/apps/notion", content=body, headers={"x-notion-signature": sig, "content-type": "application/json"})
    assert r.status_code == 202 and r.json()["event"] == "notion.page.created"
    assert wait_for_run(client, wf)["events"][0]["output"]["value"] == "got notion.page.created"


def test_webhook_setup_info(client):
    info = client.get("/api/webhooks/apps").json()
    by_app = {a["app_id"]: a for a in info}
    assert {"github", "slack", "notion"} <= set(by_app)
    assert by_app["slack"]["path"] == "/api/webhooks/apps/slack" and by_app["slack"]["secret_env"] == "NEXUS_SLACK_SIGNING_SECRET"
    assert isinstance(by_app["slack"]["configured"], bool) and by_app["slack"]["steps"]

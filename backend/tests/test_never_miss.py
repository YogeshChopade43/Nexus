"""Scheduled runs are never silently lost: late runs still fire, missed ones catch up, failures reach the phone."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.triggers.models import TriggerConfig
from app.workflows import scheduler

UTC = timezone.utc
DAILY_1PM = TriggerConfig(type="recurrence", frequency="day", interval=1, at="13:00", timezone="UTC")


def test_a_run_missed_while_nexus_was_off_is_found():
    now = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
    since = now - timedelta(hours=12)
    assert scheduler.missed_run(DAILY_1PM, None, since, now) == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    # Already ran after it was due: nothing missed.
    assert scheduler.missed_run(DAILY_1PM, "2026-10-12T13:00:05Z", since, now) is None
    # Not due yet today, and yesterday's is outside the window.
    assert scheduler.missed_run(DAILY_1PM, None, datetime(2026, 10, 12, 1, 0, tzinfo=UTC), datetime(2026, 10, 12, 12, 0, tzinfo=UTC)) is None


def test_every_minute_workflows_are_not_caught_up():
    every_minute = TriggerConfig(type="recurrence", frequency="minute", interval=5, timezone="UTC")
    now = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
    assert scheduler.missed_run(every_minute, None, now - timedelta(hours=2), now) is None


def test_cron_schedules_are_caught_up_too():
    weekdays_9 = TriggerConfig(type="schedule", schedule="0 9 * * 1-5", timezone="UTC")
    now = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)  # a Monday
    assert scheduler.missed_run(weekdays_9, "2026-10-09T09:00:01Z", now - timedelta(hours=12), now) == datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


REMINDER = {"name": "Pills", "description": "Daily at 1 pm", "isActive": True, "edges": [{"source": "t", "target": "n"}],
            "nodes": [{"id": "t", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day", "at": "13:00", "timezone": "UTC"}},
                      {"id": "n", "type": "action", "config": {"tool": "nexus__notify", "parameters": {"title": "Take your medicines"}}}]}


def test_late_runs_still_fire_after_the_computer_wakes(client):
    created = client.post("/api/workflows", json=REMINDER).json()
    job = scheduler._scheduler.get_job(f"workflow-{created['id']}")
    assert job.misfire_grace_time >= 6 * 3600
    client.delete(f"/api/workflows/{created['id']}")


def test_catch_up_runs_the_missed_reminder_and_says_when_it_was_due(client, monkeypatch):
    from app.integrations import telegram

    created = client.post("/api/workflows", json=REMINDER).json()
    due = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    monkeypatch.setattr(scheduler, "missed_run", lambda config, last_run, since, now: due if config.type == "recurrence" else None)
    forwarded = []

    async def phone(title, message=""):
        forwarded.append(title)

    monkeypatch.setattr(telegram, "notify_all", phone)
    ran = client.portal.call(scheduler.catch_up_missed_runs)
    assert created["id"] in ran
    activity = client.get("/api/activity", params={"limit": 20}).json()
    reminder = next(a for a in (activity if isinstance(activity, list) else activity["activities"]) if a["type"] == "reminder")
    assert reminder["title"].startswith("Take your medicines (was due at")
    assert forwarded and forwarded[0].startswith("Take your medicines (was due at")
    client.delete(f"/api/workflows/{created['id']}")


def test_failed_runs_reach_the_phone(client, monkeypatch):
    from app.integrations import telegram

    sent = []

    async def phone(title, message=""):
        sent.append((title, message))

    monkeypatch.setattr(telegram, "notify_all", phone)
    broken = client.post("/api/workflows", json={**REMINDER, "name": "Broken", "nodes": [
        REMINDER["nodes"][0], {"id": "n", "type": "action", "config": {"tool": "missing__tool", "parameters": {}}}]}).json()
    client.post(f"/api/workflows/{broken['id']}/run", json={})
    assert any("Broken" in title and "failed" in title for title, _ in sent)
    client.delete(f"/api/workflows/{broken['id']}")


def test_status_says_whether_everything_works(client):
    status = client.get("/api/dashboard/status").json()
    assert status["scheduler"]["running"] is True and isinstance(status["scheduler"]["jobs"], int)
    assert {"apps", "last_failure", "telegram_linked"} <= set(status)


def test_cron_weekdays_mean_what_they_mean_in_standard_cron():
    """APScheduler counts weekdays from Monday = 0; cron from Sunday = 0. '1-5' must be Monday to Friday."""
    trigger = scheduler.cron_trigger(TriggerConfig(type="schedule", schedule="0 9 * * 1-5", timezone="UTC"))
    days, cursor = [], datetime(2026, 10, 11, tzinfo=UTC)  # a Sunday
    for _ in range(5):
        cursor = trigger.get_next_fire_time(None, cursor)
        days.append(cursor.strftime("%a"))
        cursor += timedelta(hours=1)
    assert days == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    sundays = scheduler.cron_trigger(TriggerConfig(type="schedule", schedule="0 9 * * 0,7", timezone="UTC"))
    assert sundays.get_next_fire_time(None, datetime(2026, 10, 12, tzinfo=UTC)).strftime("%a") == "Sun"

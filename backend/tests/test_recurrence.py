from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.triggers.models import TriggerConfig
from app.workflows import recurrence

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=ZoneInfo("UTC"))


def cfg(**kwargs) -> TriggerConfig:
    return TriggerConfig(type="recurrence", **kwargs)


def local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def test_minute_interval():
    runs = recurrence.next_runs(cfg(frequency="minute", interval=15), now=NOW)
    assert runs[1] - runs[0] == timedelta(minutes=15)
    assert runs[2] - runs[1] == timedelta(minutes=15)


def test_minute_floor():
    with pytest.raises(ValueError, match="interval"):
        recurrence.validate(cfg(frequency="minute", interval=4))


def test_daily_at_time():
    runs = recurrence.next_runs(cfg(frequency="day", at="09:30", timezone="Asia/Kolkata"), now=NOW)
    assert all((local(r, "Asia/Kolkata").hour, local(r, "Asia/Kolkata").minute) == (9, 30) for r in runs)
    assert runs[1] - runs[0] == timedelta(days=1)


def test_every_two_days():
    runs = recurrence.next_runs(cfg(frequency="day", interval=2, at="09:00"), now=NOW)
    assert all(local(r, "UTC").hour == 9 for r in runs)
    assert runs[1] - runs[0] == timedelta(days=2)


def test_weekly_weekdays():
    runs = recurrence.next_runs(cfg(frequency="week", weekdays=["mon", "wed"], at="10:00"), now=NOW)
    assert {r.strftime("%a") for r in runs} <= {"Mon", "Wed"}
    assert len(runs) == 3


def test_week_interval_needs_sane_range():
    with pytest.raises(ValueError):
        recurrence.validate(cfg(frequency="week", interval=0, weekdays=["mon"]))


def test_week_requires_weekday():
    with pytest.raises(ValueError):
        recurrence.validate(cfg(frequency="week", weekdays=[]))


def test_monthly_day():
    runs = recurrence.next_runs(cfg(frequency="month", month_day=31, at="08:00"), now=NOW)
    assert all(r.day == 31 for r in runs)
    assert [r.month for r in runs] == [10, 12, 1]


def test_dst_keeps_wall_clock():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("UTC"))
    runs = recurrence.next_runs(cfg(frequency="day", at="09:00", timezone="America/New_York"), count=5, now=now)
    assert all(local(r, "America/New_York").hour == 9 for r in runs)


def test_bad_timezone():
    with pytest.raises(ValueError):
        recurrence.validate(cfg(frequency="day", timezone="Mars/Base"))


def test_bad_at():
    with pytest.raises(ValueError):
        recurrence.validate(cfg(frequency="day", at="25:00"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_preview_endpoint(client):
    r = client.post("/api/workflows/recurrence/preview", json={"frequency": "day", "at": "09:00", "timezone": "UTC"})
    assert r.status_code == 200, r.text
    assert len(r.json()["next_runs"]) == 3
    r = client.post("/api/workflows/recurrence/preview", json={"frequency": "minute", "interval": 1})
    assert r.status_code == 400


def test_recurrence_workflow_schedules_job(client):
    r = client.post("/api/workflows", json={
        "name": "daily", "isActive": True,
        "nodes": [
            {"id": "t", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day", "at": "09:00"}},
            {"id": "x", "type": "transform", "config": {"template": "hi"}},
        ],
        "edges": [{"source": "t", "target": "x"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trigger"] == "recurrence"
    assert body["trigger_config"]["next_run_at"]

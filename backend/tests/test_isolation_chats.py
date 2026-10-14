"""Two accounts: chats, memories, activity and the bell, usage and settings are each person's own."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from app.auth.owner import as_user
from app.llm.metering import record_usage, tokens_used_today
from app.main import app


@pytest.fixture(scope="module")
def ana():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def bo():
    with TestClient(app, user="bo@example.com") as c:
        yield c


def uid(email: str) -> int:
    return store._row("email = ?", email)["id"]


def test_chats_are_private(ana, bo):
    chat = ana.post("/api/agent/sessions", json={"title": "Ana's medical questions"}).json()
    sid = chat["session_id"]
    assert sid not in [s["session_id"] for s in bo.get("/api/agent/sessions").json()]
    assert sid not in [s["session_id"] for s in bo.get("/api/agent/sessions", params={"q": "medical"}).json()]
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"title": "hijacked"}} if method == "patch" else {}
        assert getattr(bo, method)(f"/api/agent/sessions/{sid}", **kwargs).status_code == 404, method
    assert ana.get(f"/api/agent/sessions/{sid}").json()["title"] == "Ana's medical questions"


def test_memories_are_private(ana, bo):
    made = ana.post("/api/knowledge/memories", json={"content": "Ana is allergic to peanuts"}).json()
    assert "Ana is allergic to peanuts" not in [m["content"] for m in bo.get("/api/knowledge/memories").json()]
    assert bo.delete(f"/api/knowledge/memories/{made['id']}").status_code == 404
    assert "Ana is allergic to peanuts" in [m["content"] for m in ana.get("/api/knowledge/memories").json()]


def test_activity_and_the_bell_are_private(ana, bo):
    ana.post("/api/workflows/", json={"name": "Ana's secret project", "nodes": [], "edges": []})
    titles = lambda c: [a["title"] for a in c.get("/api/activity/").json()["activities"]]  # noqa: E731
    assert any("Ana's secret project" in t for t in titles(ana))
    assert not any("Ana's secret project" in t for t in titles(bo))
    with as_user(uid("tester@example.com")):
        from app.core.database import log_activity

        log_activity("reminder", "Ana's pill reminder", "")
    assert "Ana's pill reminder" not in [n["title"] for n in bo.get("/api/activity/notifications").json()["items"]]
    assert "Ana's pill reminder" in [n["title"] for n in ana.get("/api/activity/notifications").json()["items"]]


def test_usage_and_budgets_are_per_person(ana, bo):
    with as_user(uid("tester@example.com")):
        before = tokens_used_today()
        record_usage(None, "openai", "m", 1000, 500)
        assert tokens_used_today() == before + 1500
    with as_user(uid("bo@example.com")):
        assert tokens_used_today() == 0  # Ana's tokens don't count against Bo's daily limit


def test_settings_and_folders_are_per_person(ana, bo):
    ana.patch("/api/settings/user", json={"timezone": "Asia/Kolkata"})
    ana.post("/api/workflows/folders", json={"name": "Ana's health"})
    assert bo.get("/api/settings/user").json()["timezone"] == "UTC"
    assert "Ana's health" not in [f["name"] for f in bo.get("/api/workflows/folders").json()]
    assert ana.get("/api/settings/user").json()["timezone"] == "Asia/Kolkata"

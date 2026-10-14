"""Two accounts: Bo can't see, change, run or export Ana's workflows, runs, versions or run-onces."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.routes import run_once
from app.main import app


@pytest.fixture(scope="module")
def ana():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def bo():
    with TestClient(app, user="bo@example.com") as c:
        yield c


@pytest.fixture(scope="module")
def anas(ana):
    wf = ana.post("/api/workflows/", json={"name": "Ana's private flow", "nodes": [
        {"id": "say", "type": "transform", "name": "Say", "config": {"template": "hi"}}], "edges": []}).json()
    run = ana.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    once = ana.post("/api/run-once", json={"name": "Ana's birthday note", "kind": "at", "at": at}).json()
    return {"wf": wf, "run": run, "once": once}


def test_bo_lists_none_of_anas(bo, anas):
    assert anas["wf"]["id"] not in [w["id"] for w in bo.get("/api/workflows/").json()]
    assert anas["once"]["id"] not in [i["id"] for i in bo.get("/api/run-once").json()["items"]]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/workflows/{wf}"),
    ("patch", "/api/workflows/{wf}"),
    ("post", "/api/workflows/{wf}/run"),
    ("get", "/api/workflows/{wf}/runs"),
    ("get", "/api/workflows/{wf}/runs/{run}"),
    ("get", "/api/workflows/{wf}/versions"),
    ("get", "/api/workflows/{wf}/export"),
    ("get", "/api/workflows/{wf}/trace"),
    ("patch", "/api/run-once/{once}"),
    ("delete", "/api/run-once/{once}"),
    ("delete", "/api/workflows/{wf}"),
])
def test_bo_cannot_reach_anas_by_id(bo, anas, method, path):
    url = path.format(wf=anas["wf"]["id"], run=anas["run"]["id"], once=anas["once"]["id"])
    kwargs = {"json": {"name": "hijacked"} if method == "patch" else {}} if method in ("patch", "post") else {}
    assert getattr(bo, method)(url, **kwargs).status_code == 404, url


def test_ana_still_has_hers(ana, anas):
    assert ana.get(f"/api/workflows/{anas['wf']['id']}").json()["name"] == "Ana's private flow"
    assert ana.get(f"/api/workflows/{anas['wf']['id']}/runs").status_code == 200
    assert anas["once"]["id"] in [i["id"] for i in ana.get("/api/run-once").json()["items"]]


def test_scheduled_work_runs_as_its_owner(ana, anas):
    """No one is signed in during a scheduled check: the run-once still runs, as Ana."""
    when = datetime.fromisoformat(anas["once"]["runsAt"].replace("Z", "+00:00"))
    done = ana.portal.call(run_once.tick, when + timedelta(minutes=1))
    assert "ran" in done
    assert ana.get("/api/run-once").json()["items"][0]["status"] in ("done", "scheduled")

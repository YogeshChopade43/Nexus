"""Section 6 reliability: resuming interrupted runs, notifications, cleanup of old records, backups."""
from __future__ import annotations

import io
import json
import sqlite3
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection, get_db_path, log_activity, purge_old_records
from app.main import app
from app.mcp import server_availability
from app.tools import get_tool_registry
from app.workflows.engine import mark_interrupted_runs, resume_interrupted_runs

from tests.test_workflow_features import by_node, compose, create, run


@pytest.fixture(scope="module")
def client():
    # From 127.0.0.1 so the localhost-only backup endpoint is allowed.
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_interrupted_run_resumes_from_where_it_stopped(client):
    wf = create(client, [compose("first", "{{ input.n }}"), compose("last", "done")], name="resumable")
    done = run(client, wf["id"], input_data={"n": 7})
    # Pretend Nexus stopped after 'first' finished: the run is still 'running' with only that step recorded.
    events = [e for e in done["events"] if e["nodeId"] == "first"]
    conn = get_connection()
    conn.execute("UPDATE workflow_runs SET status = 'running', events = ?, completed_at = NULL WHERE id = ?",
                 (json.dumps(events), done["id"]))
    conn.commit()
    conn.close()

    interrupted = mark_interrupted_runs()
    assert [r["id"] for r in interrupted] == [done["id"]]
    client.portal.call(resume_interrupted_runs, interrupted, get_tool_registry(), server_availability)

    deadline = time.time() + 10
    while time.time() < deadline:
        runs = client.get(f"/api/workflows/{wf['id']}/runs").json()["runs"]
        resumed = [r for r in runs if r["id"] != done["id"]]
        if resumed and resumed[0]["status"] != "running":
            break
        time.sleep(0.1)
    steps = by_node(resumed[0])
    assert resumed[0]["status"] == "completed", resumed[0]
    assert steps["first"].get("reused") is True and steps["first"]["output"]["value"] == 7
    assert steps["last"]["output"]["value"] == "done"
    old = next(r for r in runs if r["id"] == done["id"])
    assert old["status"] == "failed" and resumed[0]["id"] in old["error"]


def test_notifications_unread_and_read(client):
    client.post("/api/activity/notifications/read")
    assert client.get("/api/activity/notifications").json()["unread"] == 0
    time.sleep(0.01)  # timestamps must be later than the read mark
    log_activity("workflow_failed", "Workflow 'x' failed", "boom")
    log_activity("workflow_created", "not a notification")
    data = client.get("/api/activity/notifications").json()
    assert data["unread"] == 1 and data["items"][0]["title"] == "Workflow 'x' failed" and data["items"][0]["unread"]
    assert all(item["type"] != "workflow_created" for item in data["items"])
    client.post("/api/activity/notifications/read")
    assert client.get("/api/activity/notifications").json()["unread"] == 0
    # Turning off failure notifications in settings hides them.
    client.patch("/api/settings/user", json={"notifications": {"workflowFailure": False}})
    assert all(i["type"] != "workflow_failed" for i in client.get("/api/activity/notifications").json()["items"])
    client.patch("/api/settings/user", json={"notifications": {"workflowFailure": True}})


def test_purge_old_records(client):
    wf = create(client, [compose("a", "x")], name="old runs")
    recent = run(client, wf["id"])
    old = run(client, wf["id"])
    conn = get_connection()
    conn.execute("UPDATE workflow_runs SET started_at = '2020-01-01T00:00:00Z' WHERE id = ?", (old["id"],))
    conn.execute("INSERT INTO activity_log (type, title, timestamp) VALUES ('workflow_created', 'ancient', '2020-01-01T00:00:00Z')")
    conn.commit()
    conn.close()

    assert purge_old_records(0) == {"runs": 0, "activity": 0}  # 0 keeps everything
    removed = purge_old_records(30)
    assert removed["runs"] >= 1 and removed["activity"] >= 1
    ids = [r["id"] for r in client.get(f"/api/workflows/{wf['id']}/runs").json()["runs"]]
    assert recent["id"] in ids and old["id"] not in ids
    assert client.get("/api/settings/user").json()["retentionDays"] == 30


@pytest.mark.sqlite_only
def test_backup_contains_database_and_key(client):
    r = client.get("/api/settings/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(archive.namelist()) == {"nexus.db", "NEXUS_SECRET_KEY.txt", "RESTORE.txt"}
    assert archive.read("NEXUS_SECRET_KEY.txt").decode() == "test-secret"
    copy = get_db_path().parent / "restored-check.db"
    copy.write_bytes(archive.read("nexus.db"))
    try:
        conn = sqlite3.connect(copy)
        assert conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= 1
        conn.close()
    finally:
        copy.unlink()


def test_backup_refused_from_other_machines():
    with TestClient(app, client=("203.0.113.5", 50000)) as remote:
        assert remote.get("/api/settings/backup").status_code == 403

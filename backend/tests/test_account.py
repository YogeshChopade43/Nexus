"""Your account: name, password, sessions, exporting your data, and deleting the account with everything in it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app

PASSWORD = "test password 123"  # the test accounts' password (conftest)


@pytest.fixture
def cy():
    """A regular account of its own (nobody else's data is touched)."""
    with TestClient(app, user="cy@example.com") as c:
        yield c


def test_name_and_password(cy):
    assert cy.patch("/api/auth/me", json={"name": "Cy Lee"}).json()["name"] == "Cy Lee"
    assert cy.post("/api/auth/change-password", json={"current": "wrong one here", "new": "a new password"}).status_code == 403
    assert cy.post("/api/auth/change-password", json={"current": PASSWORD, "new": "short"}).status_code == 422
    assert cy.post("/api/auth/change-password", json={"current": PASSWORD, "new": "a new password"}).status_code == 204
    assert cy.get("/api/auth/me").status_code == 200  # still signed in here
    cy.post("/api/auth/change-password", json={"current": "a new password", "new": PASSWORD})  # put it back


def test_sessions_can_be_seen_and_ended(cy):
    with TestClient(app, auto_login=False) as other_device:
        other_device.post("/api/auth/login", json={"email": "cy@example.com", "password": PASSWORD})
        sessions = cy.get("/api/auth/sessions").json()
        assert len(sessions) >= 2 and sum(s["current"] for s in sessions) == 1
        other = next(s for s in sessions if not s["current"])
        assert cy.delete(f"/api/auth/sessions/{other['id']}").status_code == 204
        assert other_device.get("/api/auth/me").status_code == 401  # signed out there
        assert cy.get("/api/auth/me").status_code == 200


def test_export_has_your_data_and_no_secrets(cy):
    cy.post("/api/workflows/", json={"name": "Cy's flow", "nodes": [], "edges": []})
    cy.post("/api/knowledge/memories", json={"content": "Cy likes green tea"})
    cy.post("/api/llm/", json={"provider_name": "openai", "api_key": "sk-cy-secret", "model": "gpt-4o-mini"})
    exported = cy.get("/api/auth/export")
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["account"]["email"] == "cy@example.com"
    assert "Cy's flow" in [w["name"] for w in data["workflows"]]
    assert "Cy likes green tea" in [m["content"] for m in data["memories"]]
    assert "sk-cy-secret" not in exported.text and "password" not in str(data["account"]).lower()
    assert "tester@example.com" not in exported.text  # nobody else's


def test_deleting_an_account_removes_everything_in_it(cy):
    wf = cy.post("/api/workflows/", json={"name": "Cy's doomed flow", "nodes": [], "edges": []}).json()
    cy.post("/api/agent/sessions", json={"title": "Cy's chat"})
    assert cy.request("DELETE", "/api/auth/me", json={"password": "wrong one here"}).status_code == 403
    assert cy.request("DELETE", "/api/auth/me", json={"password": PASSWORD}).status_code == 204
    assert cy.get("/api/auth/me").status_code == 401
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'cy@example.com'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM workflows WHERE id = ?", (wf["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_sessions WHERE title = 'Cy''s chat'").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_last_admin_cannot_delete_their_account():
    with TestClient(app) as admin:  # the test account is the install's admin
        conn = get_connection()
        try:
            others = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND email != 'tester@example.com'").fetchone()[0]
        finally:
            conn.close()
        if others == 0:
            refused = admin.request("DELETE", "/api/auth/me", json={"password": PASSWORD})
            assert refused.status_code == 409 and "admin" in refused.json()["detail"].lower()

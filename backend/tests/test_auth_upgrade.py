"""Upgrading an install from before accounts: it asks for the owner account, and nothing is lost."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app


def test_upgrading_keeps_existing_data():
    with TestClient(app) as before:  # someone's Nexus before accounts existed: they have workflows
        made = before.post("/api/workflows/", json={"name": "Kept across the upgrade", "nodes": [], "edges": []}).json()
    conn = get_connection()
    try:  # ...and no accounts at all: data from before accounts has no owner
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.execute("UPDATE workflows SET user_id = NULL WHERE id = ?", (made["id"],))
        conn.commit()
    finally:
        conn.close()

    with TestClient(app, auto_login=False) as after:
        assert after.get("/api/auth/status").json()["hasUsers"] is False  # first visit: create your account
        signed = after.post("/api/auth/signup", json={"email": "owner@example.com", "password": "correct horse battery"})
        assert signed.status_code == 200 and signed.json()["isAdmin"] is True
        names = [w["name"] for w in after.get("/api/workflows/").json()]
        assert "Kept across the upgrade" in names  # still there, and the owner's
    assert made["id"]

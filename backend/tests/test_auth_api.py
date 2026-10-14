"""Signing up (the first account is the owner), logging in and out, and guessing passwords."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.database import get_connection, init_db
from app.main import app

PASSWORD = "correct horse battery"


@pytest.fixture
def anonymous():
    """A fresh install: no accounts yet, and a client that isn't signed in."""
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    auth.FAILED_LOGINS.clear()
    with TestClient(app, auto_login=False) as c:
        yield c
    auth.FAILED_LOGINS.clear()


def test_first_visit_creates_the_owner_then_signups_close(anonymous):
    status = anonymous.get("/api/auth/status").json()
    assert {k: status[k] for k in ("hasUsers", "signupsOpen", "user")} == {"hasUsers": False, "signupsOpen": True, "user": None}
    made = anonymous.post("/api/auth/signup", json={"email": "Ana@Example.com", "password": PASSWORD, "name": "Ana"})
    assert made.status_code == 200, made.text
    assert made.json() == {"id": made.json()["id"], "email": "ana@example.com", "name": "Ana", "isAdmin": True,
                           "emailVerified": False, "hasPassword": True, "google": False}
    cookie = made.headers["set-cookie"].lower()
    assert "nexus_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert anonymous.get("/api/auth/status").json()["signupsOpen"] is False
    second = anonymous.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD})
    assert second.status_code == 403 and "closed" in second.json()["detail"].lower()


def test_login_logout_me(anonymous):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    assert anonymous.get("/api/auth/me").status_code == 401
    assert anonymous.post("/api/auth/login", json={"email": " ANA@example.com", "password": PASSWORD}).status_code == 200
    assert anonymous.get("/api/auth/me").json()["email"] == "ana@example.com"
    old = anonymous.cookies.get("nexus_session")
    assert anonymous.post("/api/auth/logout").status_code == 204
    anonymous.cookies.set("nexus_session", old)  # the old cookie kept by someone: ended on the server too
    assert anonymous.get("/api/auth/me").status_code == 401


def test_wrong_login_says_nothing_specific(anonymous):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    wrong_password = anonymous.post("/api/auth/login", json={"email": "ana@example.com", "password": "not the password"})
    no_account = anonymous.post("/api/auth/login", json={"email": "who@example.com", "password": PASSWORD})
    assert wrong_password.status_code == no_account.status_code == 401
    assert wrong_password.json() == no_account.json() == {"detail": "Wrong email or password"}


def test_password_guessing_is_rate_limited(anonymous):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    for _ in range(10):
        assert anonymous.post("/api/auth/login", json={"email": "ana@example.com", "password": "guess guess guess"}).status_code == 401
    blocked = anonymous.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert blocked.status_code == 429  # even the right one, until the minute is up


def test_signups_can_be_opened_for_everyone(anonymous, monkeypatch):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    monkeypatch.setenv("NEXUS_SIGNUPS", "open")
    assert anonymous.get("/api/auth/status").json()["signupsOpen"] is True
    second = anonymous.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD})
    assert second.status_code == 200 and second.json()["isAdmin"] is False  # a regular account, not another admin

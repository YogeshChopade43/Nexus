"""Signing up (the first account is the owner), logging in and out, and guessing passwords."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.auth import store
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


def test_first_visit_creates_the_owner_and_others_can_sign_up(anonymous):
    status = anonymous.get("/api/auth/status").json()
    assert {k: status[k] for k in ("hasUsers", "signupsOpen", "user")} == {"hasUsers": False, "signupsOpen": True, "user": None}
    made = anonymous.post("/api/auth/signup", json={"email": "Ana@Example.com", "password": PASSWORD, "name": "Ana"})
    assert made.status_code == 200, made.text
    assert made.json() == {"id": made.json()["id"], "email": "ana@example.com", "name": "Ana", "isAdmin": True,
                           "emailVerified": False, "hasPassword": True, "google": False}
    cookie = made.headers["set-cookie"].lower()
    assert "nexus_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    anonymous.cookies.clear()
    assert anonymous.get("/api/auth/status").json()["signupsOpen"] is True  # open by default: a shared Nexus
    second = anonymous.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD})
    assert second.status_code == 200 and second.json()["isAdmin"] is False  # a regular account, not another admin


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


def test_signups_can_be_closed(anonymous, monkeypatch):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    monkeypatch.setenv("NEXUS_SIGNUPS", "closed")
    assert anonymous.get("/api/auth/status").json()["signupsOpen"] is False
    second = anonymous.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD})
    assert second.status_code == 403 and "closed" in second.json()["detail"].lower()


def lookup(client, email: str) -> str:
    return client.post("/api/auth/lookup", json={"email": email}).json()["next"]


def test_lookup_says_what_comes_after_the_email(anonymous, monkeypatch):
    assert lookup(anonymous, "ana@example.com") == "create"  # a fresh install: the owner's account
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    anonymous.cookies.clear()
    assert lookup(anonymous, " ANA@example.com ") == "password"
    assert lookup(anonymous, "bo@example.com") == "create"
    store.create_user("gabi@example.com", None, "Gabi", google_sub="google-1")
    assert lookup(anonymous, "gabi@example.com") == "google"  # signs in with Google, no password to ask for
    store._update_user(store._row("email = ?", "ana@example.com")["id"], "disabled = 1")
    assert lookup(anonymous, "ana@example.com") == "password"  # a disabled account isn't revealed as such
    monkeypatch.setenv("NEXUS_SIGNUPS", "closed")
    assert lookup(anonymous, "bo@example.com") == "closed"
    assert anonymous.post("/api/auth/lookup", json={"email": "not-an-email"}).status_code == 422


def test_lookup_is_rate_limited(anonymous):
    for n in range(auth.LOOKUP_LIMIT):
        anonymous.post("/api/auth/lookup", json={"email": f"user{n}@example.com"})
    assert anonymous.post("/api/auth/lookup", json={"email": "sweep@example.com"}).status_code == 429


@pytest.mark.parametrize("weak", ["aaaaaaaaaa", "1212121212", "1234567890", "password123", "ana@example.com"])
def test_signup_rejects_weak_passwords(anonymous, weak):
    r = anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": weak})
    assert r.status_code == 422, (weak, r.text)


def test_signup_is_rate_limited_per_ip(anonymous):
    for n in range(auth.SIGNUP_LIMIT):
        anonymous.post("/api/auth/signup", json={"email": f"user{n}@example.com", "password": PASSWORD})
    blocked = anonymous.post("/api/auth/signup", json={"email": "one-too-many@example.com", "password": PASSWORD})
    assert blocked.status_code == 429


def test_forgot_password_is_rate_limited(anonymous):
    anonymous.post("/api/auth/signup", json={"email": "ana@example.com", "password": PASSWORD})
    for _ in range(auth.EMAIL_LIMIT):
        anonymous.post("/api/auth/forgot-password", json={"email": "ana@example.com"})
    blocked = anonymous.post("/api/auth/forgot-password", json={"email": "ana@example.com"})
    assert blocked.status_code == 429

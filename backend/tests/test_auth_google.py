"""Sign in (and up) with Google: the code flow with a one-time state; accounts matched by Google id, then email."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth_google
from app.core.database import get_connection, init_db
from app.main import app

PROFILE = {"sub": "google-123", "email": "Ana@Gmail.com", "email_verified": True, "name": "Ana G"}


@pytest.fixture
def google(monkeypatch):
    """Google keys set, a fake Google, and a fresh install."""
    monkeypatch.setenv("NEXUS_GOOGLE_CLIENT_ID", "client-1")
    monkeypatch.setenv("NEXUS_GOOGLE_CLIENT_SECRET", "secret-1")
    monkeypatch.setenv("NEXUS_APP_URL", "https://nexus.example.com")
    profile = dict(PROFILE)
    seen: list[httpx.Request] = []

    def fake(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/token"):
            body = parse_qs(request.content.decode())
            assert body["code"] == ["good-code"] and body["client_secret"] == ["secret-1"]
            return httpx.Response(200, json={"access_token": "at-1", "token_type": "Bearer"})
        assert request.headers["authorization"] == "Bearer at-1"
        return httpx.Response(200, json=profile)

    monkeypatch.setattr(auth_google, "TRANSPORT", httpx.MockTransport(fake))
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    with TestClient(app, auto_login=False, follow_redirects=False) as c:
        yield c, profile


def start(client) -> str:
    begin = client.get("/api/auth/google/start")
    assert begin.status_code in (302, 307)
    target = urlparse(begin.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "accounts.google.com" and query["client_id"] == ["client-1"]
    assert query["redirect_uri"][0].endswith("/api/auth/google/callback") and "openid" in query["scope"][0]
    return query["state"][0]


def test_first_google_sign_in_creates_the_owner(google):
    client, _ = google
    assert client.get("/api/auth/status").json()["google"] is True
    state = start(client)
    back = client.get("/api/auth/google/callback", params={"code": "good-code", "state": state})
    assert back.status_code in (302, 307) and back.headers["location"] == "https://nexus.example.com/"
    me = client.get("/api/auth/me").json()
    assert me["email"] == "ana@gmail.com" and me["google"] is True and me["emailVerified"] is True and me["isAdmin"] is True


def test_a_state_works_once_and_a_made_up_one_never(google):
    client, _ = google
    state = start(client)
    client.get("/api/auth/google/callback", params={"code": "good-code", "state": state})
    client.cookies.clear()
    for bad in (state, "made-up"):
        back = client.get("/api/auth/google/callback", params={"code": "good-code", "state": bad})
        assert back.headers["location"].startswith("https://nexus.example.com/login?error=")
    assert client.get("/api/auth/me").status_code == 401


def test_google_links_an_existing_account_with_the_same_verified_email(google):
    client, _ = google
    client.post("/api/auth/signup", json={"email": "ana@gmail.com", "password": "correct horse battery"})
    client.cookies.clear()
    client.get("/api/auth/google/callback", params={"code": "good-code", "state": start(client)})
    me = client.get("/api/auth/me").json()
    assert me["email"] == "ana@gmail.com" and me["google"] is True and me["hasPassword"] is True  # one account


def test_an_unverified_google_email_is_not_linked(google):
    client, profile = google
    client.post("/api/auth/signup", json={"email": "ana@gmail.com", "password": "correct horse battery"})
    client.cookies.clear()
    profile["email_verified"] = False
    back = client.get("/api/auth/google/callback", params={"code": "good-code", "state": start(client)})
    assert "error=" in back.headers["location"]  # someone else could claim that address at Google
    assert client.get("/api/auth/me").status_code == 401


def test_new_google_accounts_follow_the_sign_up_setting(google, monkeypatch):
    client, profile = google
    client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "correct horse battery"})
    client.cookies.clear()
    back = client.get("/api/auth/google/callback", params={"code": "good-code", "state": start(client)})
    assert "error=" in back.headers["location"] and "closed" in back.headers["location"].lower()
    monkeypatch.setenv("NEXUS_SIGNUPS", "open")
    client.get("/api/auth/google/callback", params={"code": "good-code", "state": start(client)})
    assert client.get("/api/auth/me").json()["isAdmin"] is False


def test_without_google_keys_there_is_no_google_button(monkeypatch):
    monkeypatch.delenv("NEXUS_GOOGLE_CLIENT_ID", raising=False)
    with TestClient(app, auto_login=False, follow_redirects=False) as c:
        assert c.get("/api/auth/status").json()["google"] is False
        assert c.get("/api/auth/google/start").status_code == 404

"""Email: verifying a new account, and resetting a forgotten password, through one-time links."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.database import get_connection, init_db
from app.main import app

PASSWORD = "correct horse battery"


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    """Email delivery set up (to a folder), sign-ups open, and a fresh install with its owner already made."""
    monkeypatch.setenv("NEXUS_MAIL_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_SIGNUPS", "open")
    monkeypatch.setenv("NEXUS_APP_URL", "https://nexus.example.com")
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    auth.FAILED_LOGINS.clear()
    with TestClient(app, auto_login=False) as owner:
        owner.post("/api/auth/signup", json={"email": "owner@example.com", "password": PASSWORD})
    yield tmp_path


def letters(folder: Path, to: str) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.eml")) if f"To: {to}" in p.read_text(encoding="utf-8")]


def link(letter: str, path: str) -> str:
    return re.search(rf"https://nexus\.example\.com{path}\?token=([\w-]+)", letter).group(1)


def test_a_new_account_verifies_its_email_before_using_nexus(mailbox):
    with TestClient(app, auto_login=False) as bo:
        made = bo.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD}).json()
        assert made["emailVerified"] is False
        blocked = bo.get("/api/workflows/")
        assert blocked.status_code == 403 and blocked.json()["code"] == "verify_email"
        assert bo.get("/api/auth/me").status_code == 200  # can still see who they are, and resend

        token = link(letters(mailbox, "bo@example.com")[-1], "/verify-email")
        assert bo.post("/api/auth/verify-email", json={"token": token}).json()["emailVerified"] is True
        assert bo.get("/api/workflows/").status_code == 200
        assert bo.post("/api/auth/verify-email", json={"token": token}).status_code == 400  # used once


def test_resend_verification_sends_a_fresh_link(mailbox):
    with TestClient(app, auto_login=False) as bo:
        bo.post("/api/auth/signup", json={"email": "bo@example.com", "password": PASSWORD})
        assert bo.post("/api/auth/resend-verification").status_code == 204
        assert len(letters(mailbox, "bo@example.com")) == 2


def test_forgot_password_then_reset(mailbox):
    with TestClient(app, auto_login=False) as someone:
        same = [someone.post("/api/auth/forgot-password", json={"email": email}) for email in ("owner@example.com", "nobody@example.com")]
        assert [r.status_code for r in same] == [204, 204]  # never says whether there's an account
        assert letters(mailbox, "nobody@example.com") == []
        token = link(letters(mailbox, "owner@example.com")[-1], "/reset-password")

        assert someone.post("/api/auth/reset-password", json={"token": token, "password": "short"}).status_code == 422
        reset = someone.post("/api/auth/reset-password", json={"token": token, "password": "a brand new password"})
        assert reset.status_code == 200 and reset.json()["email"] == "owner@example.com"
        assert someone.get("/api/auth/me").status_code == 200  # signed in fresh
        assert someone.post("/api/auth/reset-password", json={"token": token, "password": "another new password"}).status_code == 400
        someone.cookies.clear()
        assert someone.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 401
        assert someone.post("/api/auth/login", json={"email": "owner@example.com", "password": "a brand new password"}).status_code == 200


def test_reset_ends_every_other_session(mailbox):
    with TestClient(app, auto_login=False) as laptop, TestClient(app, auto_login=False) as phone:
        laptop.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        assert laptop.get("/api/auth/me").status_code == 200
        phone.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
        token = link(letters(mailbox, "owner@example.com")[-1], "/reset-password")
        phone.post("/api/auth/reset-password", json={"token": token, "password": "a brand new password"})
        assert laptop.get("/api/auth/me").status_code == 401  # someone who had the old password is out


def test_without_email_delivery_nobody_is_held_back(monkeypatch):
    monkeypatch.delenv("NEXUS_MAIL_DIR", raising=False)
    monkeypatch.setenv("NEXUS_SIGNUPS", "open")
    init_db()
    with TestClient(app, auto_login=False) as cy:
        cy.post("/api/auth/signup", json={"email": "cy@example.com", "password": PASSWORD})
        assert cy.get("/api/workflows/").status_code == 200  # nothing can be sent, so nothing is required

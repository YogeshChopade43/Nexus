"""Accounts: hashed passwords, case-insensitive emails, sessions that end and expire."""
from __future__ import annotations

import hashlib

import pytest

from app.auth import store
from app.core.database import get_connection, init_db


@pytest.fixture(autouse=True)
def fresh():
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    yield


def test_passwords_are_hashed_and_checked():
    user = store.create_user("Ana@Example.com ", "correct horse battery", "Ana")
    assert user["email"] == "ana@example.com"
    conn = get_connection()
    try:
        stored = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()["password_hash"]
    finally:
        conn.close()
    assert stored.startswith("scrypt$16384$8$1$") and "correct horse" not in stored
    assert store.authenticate("ana@example.com", "correct horse battery")["id"] == user["id"]
    assert store.authenticate("ANA@example.com", "wrong horse battery") is None
    assert store.authenticate("nobody@example.com", "correct horse battery") is None


def test_email_and_password_rules():
    with pytest.raises(ValueError, match="email"):
        store.create_user("not-an-email", "long enough password")
    with pytest.raises(ValueError, match="10 characters"):
        store.create_user("bo@example.com", "123456789")
    store.create_user("ana@example.com", "correct horse battery")
    with pytest.raises(ValueError, match="already"):
        store.create_user("ANA@example.com", "another long password")


def test_sessions_last_until_ended_or_expired():
    user = store.create_user("ana@example.com", "correct horse battery")
    token = store.create_session(user["id"])
    assert store.user_for_session(token)["id"] == user["id"]
    conn = get_connection()
    try:
        hashes = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions").fetchall()]
    finally:
        conn.close()
    assert hashes == [hashlib.sha256(token.encode()).hexdigest()]  # the token itself is never stored
    store.end_session(token)
    assert store.user_for_session(token) is None

    expiring = store.create_session(user["id"])
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
        conn.commit()
    finally:
        conn.close()
    assert store.user_for_session(expiring) is None
    assert store.user_for_session("") is None and store.user_for_session("made-up") is None


def test_first_user_is_admin():
    first = store.create_user("ana@example.com", "correct horse battery")
    second = store.create_user("bo@example.com", "correct horse battery")
    assert store.public(first) == {"id": first["id"], "email": "ana@example.com", "name": "", "isAdmin": True,
                                   "emailVerified": False, "hasPassword": True, "google": False}
    assert store.public(second)["isAdmin"] is False and store.user_count() == 2

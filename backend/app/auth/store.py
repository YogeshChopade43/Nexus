"""Accounts and sessions.

Passwords are stored as ``scrypt$N$r$p$salt$hash`` (stdlib ``hashlib.scrypt``, 16-byte random salt); emails are
lower-cased and trimmed, so the same address with other capitals is the same account. A session is a random token
handed to the browser once (in an HttpOnly cookie); the database keeps only its SHA-256, so a copy of the database
can't be used to sign in.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.database import get_connection

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
MIN_PASSWORD = 10
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(_hash(password, salt))}"


def check_password(password: str, stored: Optional[str]) -> bool:
    try:
        _, n, r, p, salt, expected = (stored or "").split("$")
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(expected))


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters for your password")


def _row(where: str, *args: Any) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(f"SELECT * FROM users WHERE {where}", args).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_user(user_id: int) -> Optional[dict[str, Any]]:
    return _row("id = ?", user_id)


def user_count() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def create_user(email: str, password: Optional[str], name: str = "", *, email_verified: bool = False,
                google_sub: Optional[str] = None) -> dict[str, Any]:
    """A new account; the very first one is the admin. ``password`` may be None for a Google-only account."""
    email = normalise_email(email)
    if not EMAIL.match(email):
        raise ValueError("Enter a valid email address")
    if password is not None:
        check_password_rules(password)
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise ValueError("There's already an account with that email")
        first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        cursor = conn.execute(
            "INSERT INTO users (email, name, password_hash, email_verified, google_sub, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (email, (name or "").strip()[:80], hash_password(password) if password is not None else None,
             int(email_verified), google_sub, int(first), _iso(_now())))
        conn.commit()
        user_id = cursor.lastrowid
    finally:
        conn.close()
    if first:  # the install's existing data (from before accounts) is the first account's
        from app.auth.owner import claim_unowned

        claim_unowned(user_id)
    return get_user(user_id)  # type: ignore[return-value]


def authenticate(email: str, password: str) -> Optional[dict[str, Any]]:
    user = _row("email = ?", normalise_email(email))
    if user is None:
        check_password(password, hash_password("x" * MIN_PASSWORD))  # same work either way: no timing hint
        return None
    if user["disabled"] or not check_password(password, user["password_hash"]):
        return None
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn = get_connection()
    try:
        conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
                     (_token_hash(token), user_id, _iso(now), _iso(now + timedelta(days=SESSION_DAYS)), user_agent[:200]))
        conn.commit()
    finally:
        conn.close()
    return token


def user_for_session(token: Optional[str]) -> Optional[dict[str, Any]]:
    """The signed-in user for this token: None when unknown, signed out, expired or the account is disabled."""
    if not token:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (_token_hash(token),)).fetchone()
    finally:
        conn.close()
    if row is None or row["expires_at"] <= _iso(_now()):
        return None
    user = get_user(row["user_id"])
    return user if user and not user["disabled"] else None


def end_session(token: Optional[str]) -> None:
    if not token:
        return
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()
    finally:
        conn.close()


def public(user: dict[str, Any]) -> dict[str, Any]:
    """What the app may show about an account (never the password hash)."""
    return {"id": user["id"], "email": user["email"], "name": user["name"], "isAdmin": bool(user["is_admin"]),
            "emailVerified": bool(user["email_verified"]), "hasPassword": bool(user["password_hash"]),
            "google": bool(user["google_sub"])}


# ---- one-time links (verify an email, reset a password) ----

def issue_token(user_id: int, purpose: str, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_connection()
    try:
        conn.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
                     (_token_hash(token), user_id, purpose, _iso(_now() + timedelta(hours=hours))))
        conn.commit()
    finally:
        conn.close()
    return token


def use_token(token: str, purpose: str) -> Optional[int]:
    """The account a valid, unused, unexpired link is for (and it's used up now); None otherwise."""
    if not token:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT user_id, expires_at, used_at FROM email_tokens WHERE token_hash = ? AND purpose = ?",
                           (_token_hash(token), purpose)).fetchone()
        if row is None or row["used_at"] or row["expires_at"] <= _iso(_now()):
            return None
        conn.execute("UPDATE email_tokens SET used_at = ? WHERE token_hash = ?", (_iso(_now()), _token_hash(token)))
        conn.commit()
        return int(row["user_id"])
    finally:
        conn.close()


def mark_verified(user_id: int) -> None:
    _update_user(user_id, "email_verified = 1")


def set_password(user_id: int, password: str) -> None:
    check_password_rules(password)
    _update_user(user_id, "password_hash = ?", hash_password(password))


def end_all_sessions(user_id: int, keep: Optional[str] = None) -> None:
    """Sign out everywhere (except ``keep``, the current session's token)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                     (user_id, _token_hash(keep) if keep else ""))
        conn.commit()
    finally:
        conn.close()


def _update_user(user_id: int, assignment: str, *args: Any) -> None:
    conn = get_connection()
    try:
        conn.execute(f"UPDATE users SET {assignment} WHERE id = ?", (*args, user_id))
        conn.commit()
    finally:
        conn.close()


def needs_verification(user: dict[str, Any]) -> bool:
    """Has to confirm their email before using Nexus: only when email can be sent, never the owner (admin)."""
    from app.auth import mailer

    return mailer.configured() and not user["email_verified"] and not user["is_admin"]

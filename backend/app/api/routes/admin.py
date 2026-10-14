"""The admin's page: everyone's accounts, instance settings, and what a published Nexus still needs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import quota
from app.auth import store
from app.auth.context import require_admin
from app.core.database import get_connection, get_db_path, is_postgres

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin_row(user: dict[str, Any], tokens: int) -> dict[str, Any]:
    return {**store.public(user), "disabled": bool(user["disabled"]), "createdAt": user["created_at"],
            "tokens30d": tokens, "storageBytes": quota.storage_used(int(user["id"]))}


@router.get("/users")
def users() -> list[dict[str, Any]]:
    require_admin("The list of accounts")
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]
        tokens = {r["user_id"]: int(r["total"]) for r in conn.execute(
            "SELECT user_id, SUM(input_tokens + output_tokens) AS total FROM llm_usage WHERE timestamp >= ? "
            "GROUP BY user_id", (since,))}
    finally:
        conn.close()
    return [_admin_row(row, tokens.get(row["id"], 0)) for row in rows]


class UserChange(BaseModel):
    disabled: Optional[bool] = None
    isAdmin: Optional[bool] = None


@router.patch("/users/{user_id}")
def change_user(user_id: int, body: UserChange) -> dict[str, Any]:
    me = require_admin("Changing accounts")
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    if user_id == me["id"] and (body.disabled or body.isAdmin is False):
        raise HTTPException(status_code=409, detail="You can't disable your own account or remove your own admin role.")
    if body.disabled is not None:
        store._update_user(user_id, "disabled = ?", int(body.disabled))
        if body.disabled:
            store.end_all_sessions(user_id)
    if body.isAdmin is not None:
        store._update_user(user_id, "is_admin = ?", int(body.isAdmin))
    return next(u for u in users() if u["id"] == user_id)


class InstanceChange(BaseModel):
    signups: Optional[Literal["open", "closed"]] = None
    storageLimitMb: Optional[int] = Field(default=None, ge=0, le=10_000_000)


@router.get("/instance")
def get_instance() -> dict[str, Any]:
    require_admin("Instance settings")
    return quota.instance()


@router.patch("/instance")
def change_instance(body: InstanceChange) -> dict[str, Any]:
    require_admin("Instance settings")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("storageLimitMb") is None:
        changes.pop("storageLimitMb", None)
    return quota.save_instance(changes)


def _check(check_id: str, title: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "title": title, "ok": ok, "detail": detail}


@router.get("/deployment")
def deployment(request: Request) -> list[dict[str, Any]]:
    """What a Nexus reachable from the internet should have; each item says how to fix it."""
    from app.api.routes import auth_google
    from app.auth import mailer

    require_admin("The deployment checklist")
    key_file = (get_db_path().parent / ".nexus_secret_key").exists()
    public_url = os.getenv("NEXUS_PUBLIC_URL") or os.getenv("NEXUS_APP_URL") or ""
    https = public_url.startswith("https://") or request.url.scheme == "https"
    hosts = [h for h in os.getenv("NEXUS_ALLOWED_HOSTS", "").split(",") if h.strip()]
    signups_open = quota.signups_setting()
    return [
        _check("secret_key", "Encryption key", not key_file,
               "Set in the environment." if not key_file else
               "Generated into a file next to the database. Set NEXUS_SECRET_KEY yourself and keep a copy: it decrypts "
               "every stored key and token."),
        _check("database", "Database", is_postgres(),
               "PostgreSQL." if is_postgres() else "SQLite (one file). For many users, set DATABASE_URL to PostgreSQL."),
        _check("https", "HTTPS", https,
               f"Served at {public_url}." if https else
               "Put Nexus behind a TLS proxy (Caddy, nginx) and set NEXUS_PUBLIC_URL and NEXUS_APP_URL to its https:// address."),
        _check("allowed_hosts", "Domain name", bool(hosts),
               f"Answers to {', '.join(hosts)}." if hosts else "Set NEXUS_ALLOWED_HOSTS to your domain (e.g. nexus.example.com)."),
        _check("email", "Email", mailer.configured(),
               "Verification and password-reset emails are sent." if mailer.configured() else
               "Set NEXUS_SMTP_HOST (or NEXUS_RESEND_API_KEY) so people can verify their address and reset passwords."),
        _check("google", "Google sign-in", auth_google.configured(),
               "On." if auth_google.configured() else "Optional: set NEXUS_GOOGLE_CLIENT_ID and NEXUS_GOOGLE_CLIENT_SECRET."),
        _check("signups", "Sign-ups", True,
               "Anyone can create an account." if signups_open else "Closed: only existing accounts can sign in."),
    ]

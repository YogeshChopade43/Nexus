"""Your account: name, password, sessions, exporting your data, and deleting the account with everything in it.

Under /api/auth (the sign-in middleware leaves it open), so every route here checks the session itself.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.routes.auth import COOKIE, session_user
from app.auth import store
from app.auth.owner import as_user
from app.core.database import get_connection, get_db_path

router = APIRouter(prefix="/api/auth", tags=["account"])


class NameIn(BaseModel):
    name: str = Field(max_length=80)


class PasswordChange(BaseModel):
    current: str = Field(default="", max_length=200)
    new: str = Field(max_length=200)


class DeleteIn(BaseModel):
    password: str = Field(default="", max_length=200)
    confirm_email: str = Field(default="", max_length=254)  # Google-only accounts (no password) confirm by email


def _me(request: Request) -> dict[str, Any]:
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to use Nexus")
    return user


def _rows(conn, query: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, args).fetchall()]


@router.patch("/me")
def rename(body: NameIn, request: Request) -> dict[str, Any]:
    user = _me(request)
    store._update_user(user["id"], "name = ?", body.name.strip())
    return store.public(store.get_user(user["id"]))


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, request: Request) -> Response:
    """Needs the current password (a Google-only account sets its first one freely); signs out your other devices."""
    user = _me(request)
    if user["password_hash"] and not store.check_password(body.current, user["password_hash"]):
        raise HTTPException(status_code=403, detail="Your current password isn't right")
    try:
        store.set_password(user["id"], body.new)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.end_all_sessions(user["id"], keep=request.cookies.get(COOKIE))
    return Response(status_code=204)


@router.get("/sessions")
def sessions(request: Request) -> list[dict[str, Any]]:
    user = _me(request)
    current = store._token_hash(request.cookies.get(COOKIE) or "")
    conn = get_connection()
    try:
        rows = _rows(conn, "SELECT token_hash, created_at, expires_at, user_agent FROM sessions WHERE user_id = ? "
                           "ORDER BY created_at DESC", user["id"])
    finally:
        conn.close()
    return [{"id": r["token_hash"][:16], "createdAt": r["created_at"], "expiresAt": r["expires_at"],
             "userAgent": r["user_agent"], "current": r["token_hash"] == current} for r in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def end_session(session_id: str, request: Request) -> Response:
    user = _me(request)
    conn = get_connection()
    try:
        ended = conn.execute("DELETE FROM sessions WHERE user_id = ? AND substr(token_hash, 1, 16) = ?",
                             (user["id"], session_id[:16])).rowcount
        conn.commit()
    finally:
        conn.close()
    if not ended:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)


@router.get("/export")
def export(request: Request) -> Response:
    """Everything in your account as one JSON file (never your keys or passwords)."""
    from app.api.routes.settings import load_user_settings
    from app.rag.store import user_workspace

    user = _me(request)
    with as_user(user["id"]):
        conn = get_connection()
        try:
            data = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "account": {k: v for k, v in store.public(user).items() if k != "hasPassword"},
                "workflows": _rows(conn, "SELECT id, name, description, nodes, edges, trigger, folder, created_at FROM workflows "
                                         "WHERE user_id = ? ORDER BY id", user["id"]),
                "chats": _rows(conn, "SELECT session_id, title, messages, created_at, updated_at FROM agent_sessions "
                                     "WHERE user_id = ? ORDER BY id", user["id"]),
                "memories": _rows(conn, "SELECT content, source, created_at FROM memories WHERE user_id = ? ORDER BY id", user["id"]),
                "ai_providers": _rows(conn, "SELECT provider_name, model, base_url FROM llm_providers WHERE user_id = ?", user["id"]),
                "mcp_servers": _rows(conn, "SELECT name, transport, url FROM mcp_servers WHERE user_id = ?", user["id"]),
                "integrations": _rows(conn, "SELECT kind, name, created_at FROM integrations WHERE user_id = ?", user["id"]),
                "documents": _rows(conn, "SELECT c.name AS library, d.name, d.status, d.created_at FROM documents d "
                                         "JOIN collections c ON c.id = d.collection_id WHERE d.workspace_id = ?", user_workspace()),
                "settings": load_user_settings(),
            }
        finally:
            conn.close()
    for workflow in data["workflows"]:
        for key in ("nodes", "edges"):
            workflow[key] = json.loads(workflow[key] or "[]")
    for chat in data["chats"]:
        chat["messages"] = json.loads(chat["messages"] or "[]")
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="nexus-export.json"'})


async def delete_everything(user_id: int) -> None:
    """Remove an account and everything in it: apps (disconnected first), workflows and their runs, chats, documents,
    memories, activity, usage, settings, files, sessions."""
    from app.integrations import integration_manager
    from app.mcp import mcp_manager
    from app.rag import store as rag_store
    from app.workflows.scheduler import sync_workflow_schedule

    conn = get_connection()
    try:
        integrations = [r["id"] for r in _rows(conn, "SELECT id FROM integrations WHERE user_id = ?", user_id)]
        servers = [r["id"] for r in _rows(conn, "SELECT id FROM mcp_servers WHERE user_id = ?", user_id)]
        workflows = [r["id"] for r in _rows(conn, "SELECT id FROM workflows WHERE user_id = ?", user_id)]
        workspaces = [r["id"] for r in _rows(conn, "SELECT id FROM workspaces WHERE user_id = ?", user_id)]
        collections = [r["id"] for r in _rows(conn, f"SELECT id FROM collections WHERE workspace_id IN ({','.join('?' * len(workspaces)) or 'NULL'})", *workspaces)]
    finally:
        conn.close()
    for integration_id in integrations:
        integration_manager.remove(integration_id)
        shutil.rmtree(get_db_path().parent / "browser" / str(integration_id), ignore_errors=True)
    for server_id in servers:
        await mcp_manager.apply(None, server_id)
    for collection_id in collections:
        rag_store.delete_collection(collection_id)

    marks = ",".join("?" * len(workflows)) or "NULL"
    conn = get_connection()
    try:
        for child in ("workflow_run_steps", "workflow_runs", "workflow_versions", "run_once", "trigger_state",
                      "schedules", "webhook_endpoints"):
            conn.execute(f"DELETE FROM {child} WHERE workflow_id IN ({marks})", workflows)
        for table in ("workflows", "agent_sessions", "memories", "activity_log", "llm_usage", "user_settings",
                      "llm_providers", "mcp_servers", "integrations", "workspaces", "sessions", "email_tokens"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    for workflow_id in workflows:
        sync_workflow_schedule(workflow_id)  # no workflow any more: its schedule goes too
    shutil.rmtree(get_db_path().parent / "files" / str(user_id), ignore_errors=True)


@router.delete("/me", status_code=204)
async def delete_account(body: DeleteIn, request: Request) -> Response:
    user = _me(request)
    if user["password_hash"]:
        if not store.check_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=403, detail="Your password isn't right")
    elif store.normalise_email(body.confirm_email) != user["email"]:
        raise HTTPException(status_code=403, detail="Type your email address to confirm")
    if user["is_admin"]:
        conn = get_connection()
        try:
            admins = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND disabled = 0").fetchone()[0]
        finally:
            conn.close()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="You're this Nexus's only admin: make someone else an admin first.")
    await delete_everything(user["id"])
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response

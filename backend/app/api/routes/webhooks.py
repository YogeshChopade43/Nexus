"""Inbound webhooks that start workflows.

* ``POST /api/webhooks/workflows/{id}?token=...`` runs one workflow whose trigger type
  is ``webhook``. The token is generated when the workflow is saved.
* ``POST /api/webhooks/apps/{app_id}`` receives app events (GitHub natively, or the
  generic ``{"event": "...", "payload": {...}}`` shape) and runs every workflow whose
  ``app_event`` trigger matches. Requests must carry a valid GitHub signature
  (``NEXUS_GITHUB_WEBHOOK_SECRET``) or ``?token=`` equal to ``NEXUS_WEBHOOK_TOKEN``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.core.database import get_connection
from app.mcp import server_availability
from app.models.workflow import WorkflowRunRequest
from app.tools import get_tool_registry
from app.triggers.engine import TriggerEngine
from app.triggers.models import TriggerEvent
from app.workflows.scheduler import parse_trigger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

MAX_BODY_BYTES = 1_000_000


async def _read_payload(request: Request) -> tuple[bytes, Any]:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not body:
        return body, {}
    try:
        return body, json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body, {"raw": body.decode("utf-8", "replace")}


async def _run_in_background(workflow_id: int, trigger: dict[str, Any]) -> None:
    from app.workflows.engine import run_workflow

    app_connections = server_availability()
    try:
        await run_workflow(workflow_id, get_tool_registry(), app_connections, WorkflowRunRequest(), trigger=trigger)
    except Exception:
        logger.exception("Webhook-triggered run of workflow %s failed", workflow_id)


@router.post("/workflows/{workflow_id}", status_code=202)
async def workflow_webhook(workflow_id: int, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT trigger, enabled, is_active FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    config = parse_trigger(row["trigger"])
    token = request.query_params.get("token") or request.headers.get("x-nexus-token") or ""
    if config.type != "webhook" or not config.secret or not hmac.compare_digest(token, config.secret):
        # Same response for "wrong token" and "not a webhook workflow" so ids can't be probed.
        raise HTTPException(status_code=403, detail="Invalid webhook token")
    if not (row["enabled"] and row["is_active"]) or not config.enabled:
        raise HTTPException(status_code=409, detail="Workflow is disabled")

    _, payload = await _read_payload(request)
    trigger = {
        "type": "webhook",
        "payload": payload,
        "query": {k: v for k, v in request.query_params.items() if k != "token"},
        "headers": {k: v for k, v in request.headers.items() if k.lower().startswith(("x-", "content-type", "user-agent")) and k.lower() != "x-nexus-token"},
    }
    background.add_task(_run_in_background, workflow_id, trigger)
    return {"accepted": True, "workflow_id": workflow_id}


def github_event_name(event: str, payload: dict[str, Any]) -> str:
    """Map GitHub's X-GitHub-Event header + action to Nexus event names (see triggers.registry)."""
    action = payload.get("action") if isinstance(payload, dict) else None
    noun = {"issues": "issue", "repository": "repo", "pull_request_review": "pull_request", "create": "branch"}.get(event, event)
    if event == "pull_request" and action == "closed" and (payload.get("pull_request") or {}).get("merged"):
        action = "merged"
    if event == "pull_request" and action in ("edited", "synchronize"):
        action = "updated"
    if event == "pull_request_review" and action == "submitted":
        action = "review_submitted"
    if event == "issues" and action == "edited":
        action = "updated"
    if event == "create":
        action = "created"
    if event == "push" or not action:
        return f"github.{noun}"
    return f"github.{noun}.{action}"


def _authorized(request: Request, body: bytes) -> bool:
    github_secret = os.getenv("NEXUS_GITHUB_WEBHOOK_SECRET", "")
    signature = request.headers.get("x-hub-signature-256", "")
    if github_secret and signature:
        expected = "sha256=" + hmac.new(github_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    token = os.getenv("NEXUS_WEBHOOK_TOKEN", "")
    supplied = request.query_params.get("token") or request.headers.get("x-nexus-token") or ""
    return bool(token) and hmac.compare_digest(supplied, token)


@router.post("/apps/{app_id}", status_code=202)
async def app_webhook(app_id: str, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    body, payload = await _read_payload(request)
    if not os.getenv("NEXUS_GITHUB_WEBHOOK_SECRET") and not os.getenv("NEXUS_WEBHOOK_TOKEN"):
        raise HTTPException(
            status_code=403,
            detail="App webhooks are disabled. Set NEXUS_WEBHOOK_TOKEN (or NEXUS_GITHUB_WEBHOOK_SECRET) to enable them.",
        )
    if not _authorized(request, body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature or token")

    github_event = request.headers.get("x-github-event")
    if app_id == "github" and github_event:
        if github_event == "ping":
            return {"accepted": True, "event": "ping", "workflows": 0}
        event_name = github_event_name(github_event, payload)
    else:
        event_name = str(payload.get("event", "")) if isinstance(payload, dict) else ""
        if event_name and not event_name.startswith(f"{app_id}."):
            event_name = f"{app_id}.{event_name}"
        payload = payload.get("payload", payload) if isinstance(payload, dict) else {"value": payload}
    if not event_name:
        raise HTTPException(status_code=400, detail="Could not determine the event name")

    event = TriggerEvent(trigger_type="app_event", app_id=app_id, source="webhook", event_name=event_name, payload=payload)
    from app.triggers.engine import matching_workflows

    matches = matching_workflows(event)
    if matches:
        background.add_task(TriggerEngine().handle_event, event)
    return {"accepted": True, "event": event_name, "workflows": [m.workflow_id for m in matches]}

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
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.database import get_connection, log_activity
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


SLACK_EVENTS = {
    "message": "slack.message.received",
    "app_mention": "slack.app_mention",
    "reaction_added": "slack.reaction.added",
    "reaction_removed": "slack.reaction.removed",
    "channel_created": "slack.channel.created",
    "member_joined_channel": "slack.member.joined",
    "member_left_channel": "slack.member.left",
}
SLACK_MAX_AGE = 300  # seconds; older signed requests are replays

# What the UI shows for setting up each app's webhook. ``secret_env`` must be set for it to be accepted.
APP_SETUP = [
    {"app_id": "github", "label": "GitHub", "secret_env": "NEXUS_GITHUB_WEBHOOK_SECRET", "steps": [
        "In the repository, open Settings > Webhooks > Add webhook.",
        "Payload URL: this URL. Content type: application/json.",
        "Secret: any long random string; set the same value as NEXUS_GITHUB_WEBHOOK_SECRET in backend/.env.",
        "Choose the events to send (e.g. Issues, Pull requests) and save.",
    ]},
    {"app_id": "slack", "label": "Slack", "secret_env": "NEXUS_SLACK_SIGNING_SECRET", "steps": [
        "In api.slack.com/apps, open your app > Basic Information and copy the Signing Secret.",
        "Set it as NEXUS_SLACK_SIGNING_SECRET in backend/.env and restart the backend.",
        "Open Event Subscriptions, enable events, and paste this URL as the Request URL (Slack verifies it).",
        "Subscribe to bot events such as app_mention or message.channels, then reinstall the app.",
    ]},
    {"app_id": "notion", "label": "Notion", "secret_env": "NEXUS_NOTION_WEBHOOK_TOKEN", "steps": [
        "In notion.so/profile/integrations, open your integration > Webhooks > Create a subscription.",
        "Paste this URL and choose events (e.g. page.created). Notion sends a verification token.",
        "Copy the token from Nexus' Activity page, paste it into Notion to verify, and set it as NEXUS_NOTION_WEBHOOK_TOKEN.",
    ]},
]


def _hmac_ok(secret: str, message: bytes, supplied: str, prefix: str) -> bool:
    expected = prefix + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _authorized(app_id: str, request: Request, body: bytes) -> bool:
    headers = request.headers
    if app_id == "github" and os.getenv("NEXUS_GITHUB_WEBHOOK_SECRET") and headers.get("x-hub-signature-256"):
        return _hmac_ok(os.environ["NEXUS_GITHUB_WEBHOOK_SECRET"], body, headers["x-hub-signature-256"], "sha256=")
    if app_id == "slack" and os.getenv("NEXUS_SLACK_SIGNING_SECRET"):
        timestamp = headers.get("x-slack-request-timestamp", "")
        if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > SLACK_MAX_AGE:
            return False
        return _hmac_ok(os.environ["NEXUS_SLACK_SIGNING_SECRET"], f"v0:{timestamp}:".encode() + body,
                        headers.get("x-slack-signature", ""), "v0=")
    if app_id == "notion" and os.getenv("NEXUS_NOTION_WEBHOOK_TOKEN") and headers.get("x-notion-signature"):
        return _hmac_ok(os.environ["NEXUS_NOTION_WEBHOOK_TOKEN"], body, headers["x-notion-signature"], "sha256=")
    token = os.getenv("NEXUS_WEBHOOK_TOKEN", "")
    supplied = request.query_params.get("token") or headers.get("x-nexus-token") or ""
    return bool(token) and hmac.compare_digest(supplied, token)


def _accepting(app_id: str) -> bool:
    app_secret = next((a["secret_env"] for a in APP_SETUP if a["app_id"] == app_id), None)
    return bool(os.getenv("NEXUS_WEBHOOK_TOKEN") or (app_secret and os.getenv(app_secret)))


def _event_name(app_id: str, request: Request, payload: Any) -> tuple[str, Any]:
    if app_id == "github" and request.headers.get("x-github-event"):
        return github_event_name(request.headers["x-github-event"], payload), payload
    if app_id == "slack" and isinstance(payload, dict) and payload.get("type") == "event_callback":
        event = payload.get("event") or {}
        kind = str(event.get("type", ""))
        return SLACK_EVENTS.get(kind, f"slack.{kind}"), event
    if app_id == "notion" and isinstance(payload, dict) and payload.get("type"):
        return f"notion.{payload['type']}", payload
    name = str(payload.get("event", "")) if isinstance(payload, dict) else ""
    if name and not name.startswith(f"{app_id}."):
        name = f"{app_id}.{name}"
    return name, (payload.get("payload", payload) if isinstance(payload, dict) else {"value": payload})


@router.get("/apps")
def app_webhook_setup(request: Request) -> list[dict[str, Any]]:
    """How to point each app's webhooks at Nexus, and whether its secret is configured."""
    return [
        {**app, "path": f"/api/webhooks/apps/{app['app_id']}", "configured": bool(os.getenv(app["secret_env"]))}
        for app in APP_SETUP
    ]


@router.post("/apps/{app_id}", status_code=202)
async def app_webhook(app_id: str, request: Request, background: BackgroundTasks) -> Any:
    body, payload = await _read_payload(request)

    # Notion's one-time verification request carries the token the user must paste back into Notion.
    if app_id == "notion" and isinstance(payload, dict) and set(payload) == {"verification_token"}:
        log_activity("app_connected", "Notion webhook verification token received",
                     f"Paste this token into Notion to verify the subscription: {payload['verification_token']}",
                     {"app_id": "notion"})
        return JSONResponse({"verification_received": True})

    if not _accepting(app_id):
        setup = next((a["secret_env"] for a in APP_SETUP if a["app_id"] == app_id), None)
        hint = f"{setup} or NEXUS_WEBHOOK_TOKEN" if setup else "NEXUS_WEBHOOK_TOKEN"
        raise HTTPException(status_code=403, detail=f"Webhooks from {app_id} are disabled. Set {hint} to enable them.")
    if not _authorized(app_id, request, body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature or token")

    if app_id == "slack" and isinstance(payload, dict) and payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})
    if app_id == "github" and request.headers.get("x-github-event") == "ping":
        return {"accepted": True, "event": "ping", "workflows": []}

    event_name, event_payload = _event_name(app_id, request, payload)
    if not event_name:
        raise HTTPException(status_code=400, detail="Could not determine the event name")

    event = TriggerEvent(trigger_type="app_event", app_id=app_id, source="webhook", event_name=event_name, payload=event_payload)
    from app.triggers.engine import matching_workflows

    matches = matching_workflows(event)
    if matches:
        background.add_task(TriggerEngine().handle_event, event)
    return {"accepted": True, "event": event_name, "workflows": [m.workflow_id for m in matches]}

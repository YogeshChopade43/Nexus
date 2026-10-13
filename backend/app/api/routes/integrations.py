"""Connect, test and remove built-in integrations (email, calendar feeds, RSS...)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.core.database import log_activity
import html

from app.integrations import KINDS, google, integration_manager, store

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
CHANNELS = {"telegram", "slack", "discord"}  # chat apps: waiting until someone sends the bot its code


class IntegrationIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=60)
    config: dict[str, Any] = Field(default_factory=dict)


class GoogleStart(BaseModel):
    name: str = Field(default="Google", min_length=1, max_length=60)
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


def _kind(kind_id: str):
    kind = KINDS.get(kind_id)
    if kind is None:
        raise HTTPException(status_code=422, detail=f"Unknown integration type '{kind_id}'")
    return kind


def _view(integration: dict[str, Any], message: str = "") -> dict[str, Any]:
    """Never includes secrets; non-secret settings come back so the form can show them."""
    kind = KINDS.get(integration["kind"])
    hidden = (kind.secret_fields() if kind else set()) | google.TOKEN_KEYS | {"session_id"}
    needs_auth = (integration["kind"] == "google" and not integration["config"].get("refresh_token")) or (
        integration["kind"] in CHANNELS and not integration["config"].get("chat_id"))  # waiting for the code
    return {
        "id": integration["id"], "kind": integration["kind"], "name": integration["name"], "slug": integration["slug"],
        "enabled": integration["enabled"], "created_at": integration["created_at"],
        "settings": {k: v for k, v in integration["config"].items() if k not in hidden and not k.startswith("_")},
        "status": "needs_auth" if needs_auth else "connected" if integration["enabled"] else "stopped", "message": message,
        "tools": [tool.view() for tool in integration_manager.tools_of(integration["id"])],
    }


async def _checked(kind, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    missing = [f.label for f in kind.fields if f.required and not str(config.get(f.name) or "").strip()]
    if missing:
        raise HTTPException(status_code=422, detail=f"Fill in: {', '.join(missing)}")
    prepared = kind.prepare({k: v for k, v in config.items() if v not in (None, "")})
    try:
        return prepared, await kind.check(prepared)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc) or exc.__class__.__name__) from exc


def _redirect_uri(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/{google.CALLBACK_PATH}"


@router.get("/kinds")
def kinds(request: Request) -> list[dict[str, Any]]:
    # Google needs the address it sends people back to registered in the user's own OAuth client.
    return [{**kind.public(), **({"redirect_uri": _redirect_uri(request)} if kind.id == "google" else {})}
            for kind in KINDS.values()]


@router.post("/google/start")
def google_start(body: GoogleStart, request: Request) -> dict[str, Any]:
    """Save the user's OAuth client and hand back Google's sign-in page; the callback finishes the connection."""
    config = {k: str(v).strip() for k, v in body.config.items() if k in ("client_id", "client_secret") and str(v).strip()}
    if set(config) != {"client_id", "client_secret"}:
        raise HTTPException(status_code=422, detail="Fill in: OAuth client ID, OAuth client secret")
    integration = store.create_integration("google", body.name.strip(), config)
    return {"integration": _view(integration), "auth_url": google.auth_url(integration["id"], config, _redirect_uri(request))}


@router.post("/{integration_id}/sign-in")
def sign_in_again(integration_id: int, request: Request) -> dict[str, Any]:
    integration = store.get_integration(integration_id)
    if integration is None or integration["kind"] != "google":
        raise HTTPException(status_code=404, detail="Google integration not found")
    return {"auth_url": google.auth_url(integration_id, integration["config"], _redirect_uri(request))}


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    """Where Google sends the browser after the user signs in."""
    if error:
        message = f"Google sign-in didn't finish: {error}"
    else:
        try:
            integration = await google.finish_sign_in(state, code) if code and state else None
        except ValueError as exc:
            integration, message = None, str(exc)
        else:
            message = "This sign-in link has expired. Go back to Nexus and click Sign in again."
        if integration:
            integration_manager.apply(integration)
            log_activity("app_connected", f"Google '{integration['name']}' connected", metadata={"integration": integration["slug"]})
            message = f"Signed in as {integration['config'].get('account')}. You can close this tab and go back to Nexus."
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>Nexus · Google</title>"
                        f"<body style='font-family:system-ui;padding:2rem'><p>{html.escape(message)}</p></body>")


@router.get("")
def list_integrations() -> list[dict[str, Any]]:
    return [_view(i) for i in store.list_integrations()]


@router.post("")
async def create(body: IntegrationIn) -> dict[str, Any]:
    kind = _kind(body.kind)
    config, message = await _checked(kind, body.config)  # nothing is saved unless it works
    integration = store.create_integration(kind.id, body.name.strip(), config)
    integration_manager.apply(integration)
    log_activity("app_connected", f"{kind.title} '{integration['name']}' connected", metadata={"integration": integration["slug"]})
    return _view(integration, message)


@router.patch("/{integration_id}")
async def update(integration_id: int, body: IntegrationPatch) -> dict[str, Any]:
    current = store.get_integration(integration_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    message, config = "", None
    if body.config is not None:  # secrets left blank keep their saved value
        merged = {**current["config"], **{k: v for k, v in body.config.items() if v not in (None, "")}}
        config, message = await _checked(_kind(current["kind"]), merged)
    integration = store.update_integration(integration_id, name=body.name, enabled=body.enabled, config=config)
    integration_manager.apply(integration)
    return _view(integration, message)


@router.post("/{integration_id}/test")
async def test(integration_id: int) -> dict[str, Any]:
    integration = store.get_integration(integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    kind = _kind(integration["kind"])
    try:
        return {"ok": True, "message": f"Works. {await kind.check(kind.prepare(integration['config']))}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc) or exc.__class__.__name__}


@router.delete("/{integration_id}", status_code=204)
def delete(integration_id: int) -> Response:
    integration = store.get_integration(integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    integration_manager.remove(integration_id)
    store.delete_integration(integration_id)
    log_activity("app_disconnected", f"'{integration['name']}' removed", metadata={"integration": integration["slug"]})
    return Response(status_code=204)

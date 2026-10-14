from __future__ import annotations

import html
import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.middleware import require_local
from app.core.database import log_activity
from app.mcp import mcp_manager
from app.mcp import store

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp"])

class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    transport: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    tool_policies: dict[str, Literal["allow", "ask", "block"]] = Field(default_factory=dict)

    @field_validator("name", "command", "url")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _check_transport(self) -> "ServerIn":
        if self.transport == "stdio" and not self.command:
            raise ValueError("A command is required for a local (stdio) server")
        if self.transport == "http" and not self.url.startswith(("http://", "https://")):
            raise ValueError("A remote server needs an http(s) URL")
        return self


class ServerPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    transport: Optional[Literal["stdio", "http"]] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    enabled: Optional[bool] = None
    tool_policies: Optional[dict[str, Literal["allow", "ask", "block"]]] = None


def _require_reachable(transport: str, url: str) -> None:
    """A hosted server's address must be on the public internet, unless you're the admin (ponytail: checked when saved)."""
    from app.integrations.web import check_destination

    if transport != "stdio" and url:
        try:
            check_destination(url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))


def _require_local_for_stdio(request: Request, transport: str) -> None:
    if transport != "stdio":
        return
    from app.auth.context import require_admin

    require_admin("Running programs on the server (local MCP servers)")
    if not store.local_servers_allowed():
        raise HTTPException(status_code=422, detail="Nexus connects to hosted MCP servers only: add the server's URL.")
    if os.getenv("NEXUS_ALLOW_REMOTE_STDIO", "").lower() != "true":
        require_local(request, "Local (command) MCP servers can only be configured from the machine running Nexus.")


def _view(config: store.ServerConfig) -> dict[str, Any]:
    return {**config.public(), **mcp_manager.status(config.id)}


@router.get("/")
def list_servers() -> list[dict[str, Any]]:
    return [_view(config) for config in store.list_servers()]


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(code: str = "", state: str = "", iss: str = "", error: str = "",
                         error_description: str = "") -> HTMLResponse:
    """Where the browser lands after signing in to a hosted MCP server. Async: the code is handed to a
    connection waiting on the event loop, which a worker thread can't wake safely."""
    if error:
        message = f"Sign-in failed: {error_description or error}"
    elif code and state and mcp_manager.complete_sign_in(state, code, iss=iss or None):
        message = "Signed in. Nexus is connecting to the server; you can close this tab."
    else:
        message = "This sign-in link has expired. Go back to Nexus and click Sign in again."
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>Nexus sign-in</title>"
        f"<body style='font-family:system-ui;padding:2rem'><p>{html.escape(message)}</p></body>"
    )


@router.get("/{server_id}")
def get_server(server_id: int) -> dict[str, Any]:
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return _view(config)


@router.post("/")
async def create_server(req: ServerIn, request: Request) -> dict[str, Any]:
    _require_local_for_stdio(request, req.transport)
    _require_reachable(req.transport, req.url)
    config = store.create_server(req.model_dump())
    await mcp_manager.apply(config, config.id)
    await mcp_manager.wait_ready(config.id)
    log_activity("app_connected", f"MCP server '{config.name}' added", metadata={"server": config.slug})
    return _view(config)


@router.patch("/{server_id}")
async def update_server(server_id: int, req: ServerPatch, request: Request) -> dict[str, Any]:
    current = store.get_server(server_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Server not found")
    changes = req.model_dump(exclude_unset=True)
    transport = changes.get("transport", current.transport)
    # Changing what gets launched counts as configuring a command; toggling enabled does not.
    if set(changes) - {"enabled", "name", "tool_policies"}:
        _require_local_for_stdio(request, transport)
        _require_reachable(transport, changes.get("url", current.url))
    try:
        ServerIn(**{**current.public(), "env": current.env, "headers": current.headers, **changes})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    config = store.update_server(server_id, changes)
    await mcp_manager.apply(config, server_id)
    await mcp_manager.wait_ready(server_id)
    return _view(config)


@router.post("/{server_id}/restart")
async def restart_server(server_id: int) -> dict[str, Any]:
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    if not mcp_manager.restart(server_id):
        await mcp_manager.apply(config, server_id)
    await mcp_manager.wait_ready(server_id)
    return _view(config)


@router.post("/{server_id}/test")
async def test_server(server_id: int) -> dict[str, Any]:
    """Run one harmless read against the server and say whether it works, or what is wrong."""
    if store.get_server(server_id) is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return await mcp_manager.check(server_id)


@router.get("/{server_id}/logs")
def server_logs(server_id: int) -> dict[str, Any]:
    """Recent connection events plus the tail of a local server's own error output."""
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return mcp_manager.logs(server_id, config.slug)


@router.post("/{server_id}/sign-out")
async def sign_out(server_id: int) -> dict[str, Any]:
    """Forget the OAuth tokens of a hosted server; it asks you to sign in again on reconnect."""
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    store.set_oauth(server_id, {})
    config = store.get_server(server_id)
    await mcp_manager.apply(config, server_id)
    await mcp_manager.wait_ready(server_id)
    return _view(config)


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: int) -> Response:
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    await mcp_manager.apply(None, server_id)
    store.delete_server(server_id)
    log_activity("app_disconnected", f"MCP server '{config.name}' removed", metadata={"server": config.slug})
    return Response(status_code=204)

from __future__ import annotations

import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.database import log_activity
from app.mcp import mcp_manager
from app.mcp import store

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp"])

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    transport: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

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


def _require_local_for_stdio(request: Request, transport: str) -> None:
    """Launching commands is code execution: only allow it from this machine."""
    if transport != "stdio" or os.getenv("NEXUS_ALLOW_REMOTE_STDIO", "").lower() == "true":
        return
    host = request.client.host if request.client else ""
    if host not in _LOCAL_HOSTS:
        raise HTTPException(
            status_code=403,
            detail="Local (command) MCP servers can only be configured from the machine running Nexus.",
        )


def _view(config: store.ServerConfig) -> dict[str, Any]:
    return {**config.public(), **mcp_manager.status(config.id)}


@router.get("/")
def list_servers() -> list[dict[str, Any]]:
    return [_view(config) for config in store.list_servers()]


@router.get("/{server_id}")
def get_server(server_id: int) -> dict[str, Any]:
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return _view(config)


@router.post("/")
async def create_server(req: ServerIn, request: Request) -> dict[str, Any]:
    _require_local_for_stdio(request, req.transport)
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
    if set(changes) - {"enabled", "name"}:
        _require_local_for_stdio(request, transport)
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


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: int) -> Response:
    config = store.get_server(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Server not found")
    await mcp_manager.apply(None, server_id)
    store.delete_server(server_id)
    log_activity("app_disconnected", f"MCP server '{config.name}' removed", metadata={"server": config.slug})
    return Response(status_code=204)

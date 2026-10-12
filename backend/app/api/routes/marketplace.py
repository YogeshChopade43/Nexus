"""Marketplace: browse the local copy of the MCP Registry and install servers from it (see app/mcp/registry.py)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ValidationError

from app.api.routes.mcp import ServerIn, _view
from app.core.database import log_activity
from app.mcp import icons, mcp_manager, registry, store
from app.mcp.recipes import fill

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

INSTALL_WAIT = 8  # seconds Install waits for the new server to connect, ask for sign-in, or fail


class InstallIn(BaseModel):
    name: str = Field(max_length=300)
    values: dict[str, str] = Field(default_factory=dict)


def _title(row: dict[str, Any]) -> str:
    return registry.display_title(row["name"], row["title"] or "", row["description"] or "")


def _card(row: dict[str, Any], installed: dict[str, int]) -> dict[str, Any]:
    publisher, verified, _ = registry.publisher_info(row["name"], row["title"] or "")
    return {
        "name": row["name"], "title": _title(row), "description": row["description"],
        "publisher": publisher, "verified": verified, "official": bool(row.get("official")),
        "icon_url": row["icon_url"], "updated_at": row["updated_at"],
        "installed_server_id": installed.get(row["name"]),
        "status": mcp_manager.status(installed[row["name"]]).get("status") if row["name"] in installed else None,
    }


def _installed_cards(installed: dict[str, int]) -> list[dict[str, Any]]:
    """Every installed server: its listing's card, or a "Custom" card for servers not from the registry."""
    by_server = {server_id: name for name, server_id in installed.items()}
    cards = []
    for server in store.list_servers():
        row = registry.get_row(by_server[server.id]) if server.id in by_server else None
        cards.append(_card(row, installed) if row else {
            "name": None, "title": server.name, "description": "", "publisher": "Custom", "verified": False,
            "official": False, "icon_url": None, "updated_at": None, "installed_server_id": server.id,
            "status": mcp_manager.status(server.id).get("status"),
        })
    return cards


@router.get("")
def listings(
    q: str = Query("", max_length=200),
    kind: Literal["all", "installed"] = "all",
    sort: Literal["relevance", "updated"] = "relevance",
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    official: bool = False,
) -> dict[str, Any]:
    installed = registry.installed_map()
    if kind == "installed":
        words = q.lower().split()
        cards = [c for c in _installed_cards(installed)
                 if all(w in f"{c['title']} {c['description']} {c['publisher']} {c['name'] or ''}".lower() for w in words)]
        if sort == "updated":
            cards.sort(key=lambda c: c["updated_at"] or "", reverse=True)
        items = cards[offset:offset + limit]
    else:
        rows = registry.search(q, sort, offset, limit, official)
        items = [_card(row, installed) for row in rows]
    return {"items": items, "status": registry.status()}


@router.get("/featured")
def featured() -> dict[str, Any]:
    """The Featured shelf: well-known servers, in a fixed order."""
    installed = registry.installed_map()
    rows = [row for row in map(registry.get_row, registry.FEATURED) if row]
    return {"items": [_card(row, installed) for row in rows]}


@router.get("/item")
def item(name: str = Query(..., max_length=300)) -> dict[str, Any]:
    row = registry.get_row(name)
    if row is None:
        raise HTTPException(status_code=404, detail="Server not found in the registry")
    installed = registry.installed_map()
    server = store.get_server(installed[name]) if name in installed else None
    return {**_card(row, installed), "version": row["version"], "repository_url": row["repository_url"],
            "website_url": row["website_url"], "fields": row["install"]["fields"],
            "launch": _launch(row["install"]["template"]), "installed": _view(server) if server else None}


def _launch(template: dict[str, Any]) -> dict[str, Any]:
    """Where installing connects, with {placeholders} for the user's answers: shown before Install."""
    return {"url": template["url"], "headers": template["headers"]}


@router.get("/icon")
async def icon(name: str = Query(..., max_length=300)) -> Response:
    """A listing's logo (its own, its GitHub owner's avatar, or its domain's favicon), cached on disk."""
    row = registry.get_row(name)
    found = await icons.get_icon(row) if row else None
    if found is None:
        raise HTTPException(status_code=404, detail="No logo")
    data, media_type = found
    # SVGs can carry scripts: block everything if one is ever opened directly instead of as an <img>.
    return Response(data, media_type=media_type, headers={
        "Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


@router.post("/install")
async def install(req: InstallIn, request: Request) -> dict[str, Any]:
    row = registry.get_row(req.name)
    if row is None:
        raise HTTPException(status_code=404, detail="Server not found in the registry")
    if req.name in registry.installed_map():
        raise HTTPException(status_code=409, detail="Already installed")
    try:
        filled = fill(row["install"], req.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        config_input = ServerIn(name=_title(row)[:60], **filled).model_dump()
    except ValidationError as exc:  # only the messages: the input would echo the user's secrets
        raise HTTPException(status_code=422, detail="; ".join(error["msg"] for error in exc.errors()))
    config = store.create_server({**config_input, "registry_name": req.name})
    await mcp_manager.apply(config, config.id)
    # Catch quick outcomes (sign-in needed, instant failure); a first npx/uvx launch can download for a minute,
    # and the panel follows the status from there rather than leaving Install spinning.
    await mcp_manager.wait_ready(config.id, timeout=INSTALL_WAIT)
    log_activity("app_connected", f"MCP server '{config.name}' installed from the Marketplace",
                 metadata={"server": config.slug, "registry_name": req.name})
    return _view(config)


@router.post("/refresh")
def refresh() -> dict[str, Any]:
    return {"started": registry.start_sync()}


@router.get("/status")
def sync_status() -> dict[str, Optional[Any]]:
    return registry.status()

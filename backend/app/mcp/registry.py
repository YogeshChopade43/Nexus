"""A local copy of the official MCP Registry, for the Marketplace.

The registry API is slow (10-40 s per request) and only searches names, so Nexus keeps the
installable listings in SQLite (migration 9) and searches them itself. The first sync pages
through every latest listing; later ones ask only for what changed since the last sync.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.database import get_connection
from app.mcp import store
from app.mcp.recipes import plan

logger = logging.getLogger(__name__)

REGISTRY_URL = os.getenv("NEXUS_REGISTRY_URL", "https://registry.modelcontextprotocol.io").rstrip("/")
RETRY_DELAYS = (5, 20, 60)  # seconds before each retry of a failed page
STALE_AFTER = timedelta(hours=24)
OFFICIAL = "io.modelcontextprotocol.registry/official"
# Words that say nothing about whose product a listing is ("Linear MCP Server" is about Linear).
GENERIC_WORDS = set("mcp server servers official remote hosted api the for connector integration tools tool app by and "
                    "of plugin service model context protocol".split())
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}  # bbc.co.uk: the brand is "bbc"
# The Featured shelf: well-known servers, checked to exist in the registry (2026-10-09). Missing ones are skipped.
FEATURED = (
    "com.notion/mcp", "io.github.github/github-mcp-server", "app.linear/linear", "com.atlassian/atlassian-mcp-server",
    "com.stripe/mcp", "com.figma.mcp/mcp", "com.supabase/mcp", "com.cloudflare.mcp/mcp", "com.vercel/vercel-mcp",
    "io.github.upstash/context7", "co.huggingface/hf-mcp-server", "com.zapier/mcp",
    "com.paypal.mcp/mcp", "com.neon/mcp", "com.postman/postman-mcp-server", "com.canva.mcp/mcp", "com.gitlab/mcp",
    "ai.exa/exa", "com.airtable/mcp", "com.apify/apify-mcp-server",
    "io.github.grafana/mcp-grafana", "com.monday/monday.com", "com.webflow/mcp", "com.wix/mcp", "com.circleci/mcp",
    "io.prisma/mcp", "com.amplitude/mcp-server",
)
# Who is listed: verified publishers (a domain, not just a GitHub account), plus the hand-picked Featured shelf.
def _listed(column: str = "name") -> tuple[str, list[str]]:
    """SQL condition (and its parameters) for listings that are shown."""
    return f"({column} NOT LIKE 'io.github.%' OR {column} IN ({','.join('?' * len(FEATURED))}))", list(FEATURED)
# Listings that look like tests or unfinished work (in the name or title): off the front page, last in search.
JUNK_WORDS = re.compile(r"\b(test|staging|wip|sandbox|dummy|placeholder|hello world)\b", re.IGNORECASE)

_running = False
_task: Optional[asyncio.Task] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sync_row(conn) -> dict[str, Any]:
    row = conn.execute("SELECT last_synced_at, error FROM registry_sync WHERE id = 1").fetchone()
    return dict(row) if row else {"last_synced_at": None, "error": None}


def _save_sync(**fields: Any) -> None:
    conn = get_connection()
    try:
        current = {**_sync_row(conn), **fields}
        conn.execute("INSERT OR REPLACE INTO registry_sync (id, last_synced_at, error) VALUES (1, ?, ?)",
                     (current["last_synced_at"], current["error"]))
        conn.commit()
    finally:
        conn.close()


def status() -> dict[str, Any]:
    conn = get_connection()
    try:
        row = _sync_row(conn)
        listed, listed_params = _listed()
        count = conn.execute(f"SELECT COUNT(*) FROM registry_servers WHERE {listed}", listed_params).fetchone()[0]
    finally:
        conn.close()
    state = "syncing" if _running else ("error" if row["error"] else "idle")
    return {"status": state, "count": count, "last_synced_at": row["last_synced_at"], "error": row["error"]}


def _brand(namespace: str) -> str:
    """notion.com -> "notion", bbc.co.uk -> "bbc" (namespaces are reversed domains: com.notion)."""
    parts = namespace.split(".")
    brand = parts[1].lower() if len(parts) > 1 else ""
    return parts[2].lower() if brand in SECOND_LEVEL and len(parts) > 2 else brand


def _product_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in GENERIC_WORDS and not w.isdigit()]


def publisher_info(name: str, title: str) -> tuple[str, bool, bool]:
    """(readable publisher, verified domain, official). The registry verifies that the publisher owns the
    namespace: a GitHub account (io.github.<user>) or a domain (com.notion = notion.com). A listing is
    "Official" when it comes from a verified domain and names no product but that domain's brand
    ("com.notion/mcp" with no title is Notion's own server; "com.mcparmory/notion" is not)."""
    namespace, _, rest = name.partition("/")
    parts = namespace.split(".")
    if namespace.startswith("io.github.") and len(parts) > 2:
        return f"github.com/{'.'.join(parts[2:])}", False, False
    brand = _brand(namespace)
    official = len(brand) > 1 and all(word == brand for word in _product_words(title or rest))
    return ".".join(reversed(parts)), True, official


def _cased(word: str, description: str) -> str:
    """``word`` as the description writes it with capitals ("paypal" -> "PayPal"), else capitalised."""
    found = [m for m in re.findall(rf"\b{re.escape(word)}\b", description, re.IGNORECASE) if m != m.lower()]
    return max(set(found), key=found.count) if found else word.capitalize()


def display_title(name: str, title: str, description: str = "") -> str:
    """The listing's title; without one, its name, or the brand when the name is generic ("com.notion/mcp" -> "Notion")."""
    if title:
        return title
    namespace, _, rest = name.partition("/")
    words = _product_words(rest) or ([] if namespace.startswith("io.github.") else [_brand(namespace)])
    if not words:
        return rest or name
    return " ".join(_cased(word, description) for word in words)  # "playwright-mcp" -> "Playwright"


def is_junk(name: str, title: str, description: str) -> bool:
    """A test/staging/unfinished listing, or one with no real description (empty, tiny, or just its title)."""
    words = re.sub(r"[./_\-()]+", " ", f"{name} {title}")
    description = description.strip().lower()
    return bool(JUNK_WORDS.search(words)) or len(description) < 20 or description in (
        title.strip().lower(), name.split("/")[-1].lower())


def backfill_flags() -> None:
    """Fill the Official and junk flags for listings stored before they existed (one-off; quick)."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT name, title, description FROM registry_servers "
                            "WHERE official IS NULL OR junk IS NULL").fetchall()
        conn.executemany("UPDATE registry_servers SET official = ?, junk = ? WHERE name = ?", [
            (int(publisher_info(r["name"], r["title"] or "")[2]),
             int(is_junk(r["name"], r["title"] or "", r["description"] or "")), r["name"]) for r in rows])
        conn.commit()
    finally:
        conn.close()


def _delete(conn, name: str) -> None:
    row = conn.execute("SELECT rowid FROM registry_servers WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute("DELETE FROM registry_fts WHERE rowid = ?", (row[0],))
        conn.execute("DELETE FROM registry_servers WHERE rowid = ?", (row[0],))


def _store(conn, item: dict[str, Any]) -> None:
    server = item.get("server") or {}
    name = server.get("name")
    if not name:
        return
    meta = (item.get("_meta") or {}).get(OFFICIAL) or {}
    if meta.get("isLatest") is False:
        return  # an older version (even a deleted one) says nothing about the current listing
    if meta.get("status") == "deleted":
        _delete(conn, name)
        return
    recipe = plan(server)
    _delete(conn, name)
    if recipe is None:
        return  # Nexus can't run it (Docker, SSE-only, no install info): not listed
    icons = server.get("icons") or []
    match_key = recipe["template"]["url"]
    title, description = server.get("title") or "", server.get("description") or ""
    cursor = conn.execute(
        "INSERT INTO registry_servers (name, title, description, version, icon_url, repository_url, website_url, "
        "install_json, kind, match_key, updated_at, official, junk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, title, description, server.get("version"), (icons[0] or {}).get("src") if icons else None,
         (server.get("repository") or {}).get("url"), server.get("websiteUrl"), json.dumps(recipe),
         recipe["kind"], match_key, meta.get("updatedAt"), int(publisher_info(name, title)[2]),
         int(is_junk(name, title, description))),
    )
    conn.execute("INSERT INTO registry_fts (rowid, name, title, description) VALUES (?, ?, ?, ?)",
                 (cursor.lastrowid, name, title, description))


def _store_page(servers: list[dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        for item in servers:
            try:
                _store(conn, item)
            except Exception as exc:  # one malformed listing must not stop the sync for good
                logger.warning("Skipping malformed MCP Registry entry %r: %s", (item.get("server") or {}).get("name"), exc)
        conn.commit()  # one transaction per page
    finally:
        conn.close()


async def _get_page(client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
    error: Exception = RuntimeError("no attempt made")
    for delay in (0, *RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            response = await client.get("/v0/servers", params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            error = exc
    raise error


async def sync(transport: Optional[httpx.AsyncBaseTransport] = None) -> dict[str, Any]:
    """Bring the local copy up to date. A failure keeps what is already stored and records the error."""
    global _running
    if _running:
        return status()
    _running = True
    started = _now()
    try:
        conn = get_connection()
        try:
            since = _sync_row(conn)["last_synced_at"]
        finally:
            conn.close()
        async with httpx.AsyncClient(base_url=REGISTRY_URL, timeout=60, transport=transport) as client:
            cursor = None
            while True:
                # Incremental syncs ask for every changed version; isLatest picks the current one.
                params: dict[str, Any] = {"limit": 100, **({"updated_since": since} if since else {"version": "latest"})}
                if cursor:
                    params["cursor"] = cursor
                data = await _get_page(client, params)
                _store_page(data.get("servers") or [])
                cursor = (data.get("metadata") or {}).get("nextCursor")
                if not cursor:
                    break
        _save_sync(last_synced_at=started, error=None)
    except Exception as exc:  # network, HTTP or unexpected data: keep the old copy
        logger.warning("MCP Registry sync failed: %s", exc)
        _save_sync(error=str(exc)[:500] or exc.__class__.__name__)
    finally:
        _running = False
    return status()


def start_sync() -> bool:
    """Start a background sync unless one is running. Needs a running event loop."""
    global _task
    if _running or (_task is not None and not _task.done()):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _task = loop.create_task(sync())
    return True


def auto_sync_enabled() -> bool:
    return os.getenv("NEXUS_REGISTRY_SYNC", "on").lower() != "off"


async def stop_sync() -> None:
    """Cancel a background sync (at shutdown); pages already stored are kept."""
    if _task is not None and not _task.done():
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)


def sync_if_stale() -> None:
    if not auto_sync_enabled():
        return
    last = status()["last_synced_at"]
    if not last or datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")) > STALE_AFTER:
        start_sync()


def get_row(name: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM registry_servers WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return _decode(row) if row is not None else None


def _decode(row: Any) -> dict[str, Any]:
    return {**dict(row), "install": json.loads(row["install_json"])}


def search(q: str = "", sort: str = "relevance", offset: int = 0, limit: int = 30,
           official: bool = False) -> list[dict[str, Any]]:
    """Listings matching every word of ``q`` (prefixes, in name, title or description); official ones first.
    Only verified publishers (a domain, not just a GitHub account) are listed, plus the Featured shelf."""
    words = re.findall(r"\w+", q or "")
    listed, params = _listed("s.name")
    where: list[str] = [listed]
    if official:
        where.append("COALESCE(s.official, 0) = 1")
    # The same title from the same publisher more than once: only the newest is listed.
    where.append("NOT EXISTS (SELECT 1 FROM registry_servers d WHERE d.title = s.title AND s.title != '' "
                 "AND substr(d.name, 1, instr(d.name, '/')) = substr(s.name, 1, instr(s.name, '/')) "
                 "AND COALESCE(d.updated_at, '') > COALESCE(s.updated_at, ''))")
    by_name = "COALESCE(NULLIF(s.title, ''), s.name) COLLATE NOCASE"
    if words:
        sql = "SELECT s.* FROM registry_fts JOIN registry_servers s ON s.rowid = registry_fts.rowid"
        where.insert(0, "registry_fts MATCH ?")
        params.insert(0, " ".join(f'"{word}"*' for word in words))  # quoted: FTS syntax in q is just text
        # An official listing goes first only when the search is about it ("notion" -> Notion's own server),
        # not when its description merely mentions the words.
        about = " AND ".join("lower(COALESCE(s.title, '') || ' ' || s.name) LIKE ?" for _ in words)
        order_params = [f"%{word.lower()}%" for word in words]
        order = (f"CASE WHEN COALESCE(s.official, 0) = 1 AND {about} THEN 0 ELSE 1 END, COALESCE(s.junk, 0), "
                 "bm25(registry_fts)"
                 if sort == "relevance" else "s.updated_at DESC")
        if sort != "relevance":
            order_params = []
    else:
        sql = "SELECT s.* FROM registry_servers s"
        where.append("COALESCE(s.junk, 0) = 0")  # browsing: tests and empty listings stay off the front page
        order = f"COALESCE(s.official, 0) DESC, {by_name}" if sort == "relevance" else "s.updated_at DESC"
        order_params = []
    sql += (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}, s.name LIMIT ? OFFSET ?"
    conn = get_connection()
    try:
        return [_decode(row) for row in conn.execute(sql, (*params, *order_params, limit, offset)).fetchall()]
    finally:
        conn.close()


def installed_map() -> dict[str, int]:
    """Registry name -> installed server id: by the name saved at install, else by URL."""
    found: dict[str, int] = {}
    conn = get_connection()
    try:
        for server in store.list_servers():
            if server.registry_name:
                found.setdefault(server.registry_name, server.id)
                continue
            if server.transport != "http" or not server.url:
                continue
            for row in conn.execute("SELECT name FROM registry_servers WHERE match_key = ?", (server.url,)):
                found.setdefault(row[0], server.id)
    finally:
        conn.close()
    return found

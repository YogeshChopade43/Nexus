"""Marketplace publishers: readable names, "Verified domain" and "Official" badges, ranking, and which publishers are listed."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.main import app
from app.mcp import registry
from app.mcp.registry import publisher_info

OFFICIAL = "io.modelcontextprotocol.registry/official"
HOSTED = {"remotes": [{"type": "streamable-http", "url": "https://h.example/mcp"}]}


def listing(name, title=None, description="A Notion workspace helper"):
    return {"server": {"name": name, "title": title, "description": description, "version": "1", **HOSTED},
            "_meta": {OFFICIAL: {"status": "active", "isLatest": True}}}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        conn = get_connection()
        for table in ("registry_servers", "registry_fts", "registry_sync"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        servers = [listing("io.github.awkoy/notion-mcp-server", "Notion MCP Server"), listing("com.mcparmory/notion", "Notion"),
                   listing("ai.smithery/smithery-notion"), listing("com.notion/mcp"),
                   listing("com.avatars/avatars", "Avatars", description="Make avatars; exports to Notion")]
        asyncio.run(registry.sync(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"servers": servers, "metadata": {}}))))
        yield c


def test_publisher_info():
    assert publisher_info("com.notion/mcp", "Notion") == ("notion.com", True, True)
    assert publisher_info("app.linear/mcp", "Linear MCP Server") == ("linear.app", True, True)
    assert publisher_info("com.mcparmory/notion", "Notion") == ("mcparmory.com", True, False)
    assert publisher_info("ai.smithery/smithery-notion", "") == ("smithery.ai", True, False)
    assert publisher_info("io.github.awkoy/notion-mcp-server", "Notion MCP Server") == ("github.com/awkoy", False, False)
    # A verified domain's server that names no other product is the company's own (Notion's real listing).
    assert publisher_info("com.notion/mcp", "") == ("notion.com", True, True)


def test_cards_carry_badges_and_official_ranks_first(client):
    cards = client.get("/api/marketplace", params={"q": "notion"}).json()["items"]
    assert cards[0]["name"] == "com.notion/mcp"
    assert cards[0]["publisher"] == "notion.com" and cards[0]["official"] and cards[0]["verified"]
    front = client.get("/api/marketplace").json()["items"]  # front page: official listings first
    assert [c["official"] for c in front] == sorted((c["official"] for c in front), reverse=True)


def test_only_verified_publishers_are_listed_except_featured(client, monkeypatch):
    """GitHub-account listings are left out, unless hand-picked for the Featured shelf (GitHub's own server)."""
    names = [c["name"] for c in client.get("/api/marketplace", params={"q": "notion"}).json()["items"]]
    assert names and not any(n.startswith("io.github.") for n in names)
    monkeypatch.setattr(registry, "FEATURED", ("io.github.awkoy/notion-mcp-server",))
    names = [c["name"] for c in client.get("/api/marketplace", params={"q": "notion"}).json()["items"]]
    assert "io.github.awkoy/notion-mcp-server" in names


def test_backfill_fills_rows_stored_before_badges(client):
    conn = get_connection()
    conn.execute("UPDATE registry_servers SET official = NULL")
    conn.commit()
    conn.close()
    registry.backfill_flags()
    conn = get_connection()
    assert conn.execute("SELECT official FROM registry_servers WHERE name = 'com.notion/mcp'").fetchone()[0] == 1
    conn.close()


def test_official_ranks_first_only_for_its_own_brand(client):
    cards = client.get("/api/marketplace", params={"q": "notion"}).json()["items"]
    assert cards[0]["name"] == "com.notion/mcp"  # not com.avatars, which is official but only mentions Notion
    assert cards[0]["title"] == "Notion"  # no title and a generic name: named after the brand, not "mcp"


def test_untitled_listings_get_readable_titles():
    assert registry.display_title("com.vercel/vercel-mcp", "") == "Vercel"
    assert registry.display_title("io.github.microsoft/playwright-mcp", "") == "Playwright"
    assert registry.display_title("com.apify/apify-mcp-server", "") == "Apify"
    assert registry.display_title("io.github.x/notion_url-shape", "") == "Notion Url Shape"
    assert registry.display_title("com.notion/mcp", "") == "Notion"
    assert registry.display_title("com.x/whatever", "Given Title") == "Given Title"


def test_generated_titles_use_the_brands_own_casing():
    # Casing comes from how the listing's description writes the name, not from a list of brands.
    assert registry.display_title("com.paypal/mcp", "", "The official PayPal MCP server. paypal payments.") == "PayPal"
    assert registry.display_title("com.gitlab/gitlab-mcp", "", "Manage GitLab projects") == "GitLab"
    assert registry.display_title("com.x/github-actions", "", "Run GitHub Actions. Uses the github API.") == "GitHub Actions"
    assert registry.display_title("com.vercel/mcp", "", "deploy apps") == "Vercel"  # not mentioned: capitalised


def test_official_filter(client):
    cards = client.get("/api/marketplace", params={"official": "true", "q": "notion"}).json()["items"]
    assert cards[0]["name"] == "com.notion/mcp" and all(c["official"] for c in cards)
    assert not any(c["name"].startswith(("io.github.", "com.mcparmory", "ai.smithery")) for c in cards)
    assert all(c["official"] for c in client.get("/api/marketplace", params={"official": "true"}).json()["items"])


def test_status_counts_only_listed_servers(client):
    # 5 synced: io.github.awkoy is hidden (a GitHub account, not featured), the other 4 are listed.
    assert client.get("/api/marketplace/status").json()["count"] == 4

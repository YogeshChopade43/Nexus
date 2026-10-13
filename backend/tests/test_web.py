"""Web search (SearXNG, Brave or Tavily) and reading a web page, safely."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import web
from app.main import app
from app.mcp import server_states
from app.tools import get_tool_registry

PAGES = {
    "https://news.example.org/story": ("text/html", """<html><head><title>Nexus 1.0 ships</title><style>p{}</style></head>
        <body><nav>Home | About</nav><article><h1>Nexus 1.0 ships</h1><p>The self-hosted assistant reached 1.0 today.</p>
        <script>track()</script><p>It adds Telegram &amp; Google.</p></article><footer>Cookies</footer></body></html>"""),
    "https://short.example.org/x": ("redirect", "https://news.example.org/story"),
    "https://evil.example.org/x": ("redirect", "http://127.0.0.1:8000/api/settings"),
}


def fake_web(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.startswith("https://searx.example.org/search"):
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [{"title": "Nexus 1.0 ships", "url": "https://news.example.org/story",
                                                       "content": "The self-hosted assistant reached 1.0."}]})
    if url.startswith("https://api.search.brave.com/"):
        assert request.headers["x-subscription-token"] == "brave-key"
        return httpx.Response(200, json={"web": {"results": [{"title": "B", "url": "https://b.example.org", "description": "<b>bold</b> hit"}]}})
    if url.startswith("https://api.tavily.com/search"):
        body = json.loads(request.content)
        assert body["api_key"] == "tavily-key"
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://t.example.org", "content": "tavily hit"}]})
    kind, body = PAGES.get(url, ("missing", ""))
    if kind == "redirect":
        return httpx.Response(302, headers={"location": body})
    if kind == "missing":
        return httpx.Response(404, text="not here")
    return httpx.Response(200, text=body, headers={"content-type": kind})


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(web, "TRANSPORT", httpx.MockTransport(fake_web))
    # Public names resolve to a public address; localhost and private ranges are real-life blocked targets.
    monkeypatch.setattr(web, "_addresses", lambda host: ["127.0.0.1"] if host in ("localhost", "127.0.0.1") else
                        ["10.0.0.5"] if host == "intranet.local" else ["93.184.216.34"])


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run(name, **parameters):
    return asyncio.run(get_tool_registry().get_tool(name).execute(parameters))


def test_reading_a_page_keeps_the_article_and_drops_the_chrome():
    page = run("web__read_page", url="https://short.example.org/x")["data"]  # follows the redirect
    assert page["url"] == "https://news.example.org/story" and page["title"] == "Nexus 1.0 ships"
    assert "reached 1.0 today" in page["text"] and "Telegram & Google" in page["text"]
    assert "track()" not in page["text"] and "Cookies" not in page["text"] and "Home | About" not in page["text"]
    assert "never instructions" in run("web__read_page", url="https://news.example.org/story")["text"]


def test_private_addresses_are_refused_even_after_a_redirect():
    for url in ("http://localhost:8000/api/settings", "http://intranet.local/admin", "file:///etc/passwd",
                "https://evil.example.org/x"):
        with pytest.raises(ValueError, match="public web"):
            run("web__read_page", url=url)


def test_reading_pages_needs_no_setup(client):
    assert server_states()["web"]["available"] is True


@pytest.mark.parametrize("config,expected_url", [
    ({"searxng_url": "https://searx.example.org"}, "https://news.example.org/story"),
    ({"brave_api_key": "brave-key"}, "https://b.example.org"),
    ({"tavily_api_key": "tavily-key"}, "https://t.example.org"),
])
def test_search_providers(client, config, expected_url):
    created = client.post("/api/integrations", json={"kind": "websearch", "name": "Web search", "config": config})
    assert created.status_code == 200, created.text
    query = "nexus release"
    results = run(f"{created.json()['slug']}__search", query=query)["data"]["results"]
    assert results[0]["url"] == expected_url and "<b>" not in results[0]["snippet"]
    client.delete(f"/api/integrations/{created.json()['id']}")


def test_search_needs_one_provider(client):
    bad = client.post("/api/integrations", json={"kind": "websearch", "name": "Web search", "config": {}})
    assert bad.status_code == 422 and "SearXNG" in bad.json()["detail"]

"""RSS and Atom feeds: blogs, changelogs, news, release notes, job boards, YouTube channels, subreddits."""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

from app.integrations import base
from app.integrations.base import Field, IntegrationTool, Kind, strip_html

ATOM = "{http://www.w3.org/2005/Atom}"
FIELDS = [Field("url", "Feed address", "url", help="The RSS or Atom link of a blog, changelog, news site or YouTube channel")]


def _text(element: Any, tag: str) -> str:
    found = element.find(tag) if element is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def parse(text: str) -> tuple[str, list[dict[str, Any]]]:
    """(feed title, items newest first as published) from RSS 2.0 or Atom."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    # A real feed never declares a DOCTYPE or entities; a crafted one uses them to blow up memory (billion laughs).
    # stdlib ElementTree expands internal entities and the Python docs call it unsafe on hostile input, so refuse first.
    if re.search(rb"<!(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise ValueError("That address isn't a valid RSS or Atom feed.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError(f"That address isn't an RSS or Atom feed: {exc}") from exc
    items = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = next((l.get("href") for l in entry.findall(f"{ATOM}link") if l.get("rel") in (None, "alternate")), "")
            items.append({"id": _text(entry, f"{ATOM}id") or link, "title": _text(entry, f"{ATOM}title"), "link": link,
                          "published": _text(entry, f"{ATOM}published") or _text(entry, f"{ATOM}updated"),
                          "summary": strip_html(_text(entry, f"{ATOM}summary") or _text(entry, f"{ATOM}content"))})
        return _text(root, f"{ATOM}title"), items
    channel = root.find("channel")
    if channel is None:
        raise ValueError("That address isn't an RSS or Atom feed")
    for item in channel.findall("item"):
        link = _text(item, "link")
        items.append({"id": _text(item, "guid") or link, "title": _text(item, "title"), "link": link,
                      "published": _text(item, "pubDate"), "summary": strip_html(_text(item, "description"))})
    return _text(channel, "title"), items


async def check(config: dict[str, Any]) -> str:
    title, items = parse(await base.fetch_text(config["url"]))
    return f"Feed \"{title or config['url']}\" with {len(items)} item(s)"


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    async def latest(p: dict[str, Any]) -> Any:
        title, items = parse(await base.fetch_text(config["url"]))
        words = str(p.get("query") or "").lower()
        if words:
            items = [i for i in items if words in f"{i['title']} {i['summary']}".lower()]
        return {"feed": title, "items": items[:max(1, min(int(p.get("limit") or 10), 50))]}

    return [IntegrationTool(slug, name, "latest_items", f"The latest items of the {name} feed (title, link, date, summary), "
                            "optionally only those mentioning some words.", {
                                "properties": {"limit": {"type": "integer", "description": "How many (default 10)"},
                                               "query": {"type": "string"}}},
                            latest, title="Latest items")]


KIND = Kind("rss", "RSS / Atom feed", "Follow blogs, changelogs, news and release notes; trigger workflows on new posts.",
            "Rss", FIELDS, check, tools)

"""Marketplace logos. Only ~9% of registry listings have their own icon, so Nexus falls back to the
publisher's GitHub avatar, then the favicon of the publisher's domain. Images are fetched once by the
backend and kept on disk; listings with no logo anywhere are remembered for a week.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx

from app.core.database import get_db_path

MAX_BYTES = 200_000
TIMEOUT = 5
MISS_TTL = 7 * 24 * 3600
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests swap in a fake internet
TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "image/x-icon": "ico",
         "image/vnd.microsoft.icon": "ico", "image/svg+xml": "svg"}
EXT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "ico": "image/x-icon",
             "svg": "image/svg+xml"}


def icon_dir() -> Path:
    return get_db_path().parent / "marketplace-icons"


def candidates(row: dict[str, Any]) -> list[str]:
    """Where a listing's logo may be, best first."""
    urls = []
    if (row.get("icon_url") or "").startswith(("https://", "http://")):
        urls.append(row["icon_url"])
    namespace = row["name"].split("/")[0]
    github = namespace.startswith("io.github.")
    owner = namespace[len("io.github."):] if github else None
    if not owner and (match := re.match(r"https://github\.com/([^/?#]+)", row.get("repository_url") or "")):
        owner = match.group(1)
    if owner:
        urls.append(f"https://github.com/{quote(owner)}.png?size=80")
    domain = urlparse(row["website_url"]).hostname if row.get("website_url") else None
    if not domain and not github:
        domain = ".".join(reversed(namespace.split(".")))
    if domain:
        urls.append(f"https://icons.duckduckgo.com/ip3/{quote(domain)}.ico")
    return urls


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[tuple[bytes, str]]:
    try:
        async with client.stream("GET", url) as response:
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code != 200 or content_type not in TYPES:
                return None
            data = b""
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
            return (data, content_type) if data else None
    except httpx.HTTPError:
        return None


async def get_icon(row: dict[str, Any]) -> Optional[tuple[bytes, str]]:
    """The logo's bytes and media type, from the disk cache or the first source that has one."""
    folder = icon_dir()
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(row["name"].encode()).hexdigest()
    for path in folder.glob(key + ".*"):
        if path.suffix == ".none":
            if time.time() - path.stat().st_mtime < MISS_TTL:
                return None
            path.unlink(missing_ok=True)  # look again: the publisher may have added one
        elif path.suffix[1:] in EXT_TYPES:
            return path.read_bytes(), EXT_TYPES[path.suffix[1:]]
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, transport=TRANSPORT) as client:
        for url in candidates(row):
            found = await _fetch(client, url)
            if found:
                data, content_type = found
                (folder / f"{key}.{TYPES[content_type]}").write_bytes(data)
                return data, EXT_TYPES[TYPES[content_type]]
    (folder / f"{key}.none").touch()
    return None

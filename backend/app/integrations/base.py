"""What every built-in integration provides: a form (fields), a connection check, and tools.

Integration tools are ordinary ``Tool``s named ``<slug>__<tool>``, so the chat agent, workflows, approvals and
the activity log treat them exactly like MCP tools.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.tools.base import Tool

MAX_DOWNLOAD = 5_000_000  # bytes: a feed bigger than this is not a feed


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"  # text | password | email | url | number
    required: bool = True
    default: Any = None
    help: str = ""
    advanced: bool = False  # folded away in the form

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Kind:
    id: str
    title: str
    description: str
    icon: str  # a Lucide icon name for the UI
    fields: list[Field]
    check: Callable[[dict[str, Any]], Awaitable[str]]  # raises with a readable message, or says what it found
    tools: Callable[[str, str, dict[str, Any]], list["IntegrationTool"]]
    prepare: Callable[[dict[str, Any]], dict[str, Any]] = field(default=lambda config: config)
    # Something that keeps running while connected (a Telegram bot), started with the integration's id and settings.
    start: Optional[Callable[[int, dict[str, Any]], Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)  # more for the setup form (Slack's app manifest)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "description": self.description, "icon": self.icon,
                "fields": [f.public() for f in self.fields], **self.extra}

    def secret_fields(self) -> set[str]:
        return {f.name for f in self.fields if f.type == "password"}


class IntegrationTool(Tool):
    """One action of a connected integration. ``run`` returns plain data; it is sent as JSON text plus ``data``."""

    def __init__(self, slug: str, app_name: str, name: str, description: str, schema: dict[str, Any],
                 run: Callable[[dict[str, Any]], Awaitable[Any]], read_only: bool = True, title: Optional[str] = None,
                 policy: Optional[str] = None) -> None:
        super().__init__(f"{slug}__{name}", slug, f"[{app_name}] {description}")
        self.remote_name = name
        self.title = title
        self.read_only = read_only
        self.destructive = not read_only
        # Anything that changes data waits for an Approve, unless it is harmless (saving a draft sends nothing).
        self.policy = policy or ("allow" if read_only else "ask")
        self._schema = {"type": "object", "properties": {}, **schema}
        self._run = run

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        data = await self._run(parameters or {})
        return {"text": data if isinstance(data, str) else json.dumps(data, default=str), "data": data}

    def view(self) -> dict[str, Any]:
        return {"name": self.tool_name, "remote_name": self.remote_name, "description": self.description,
                "policy": self.policy, "title": self.title, "read_only": self.read_only,
                "destructive": self.destructive, "required": list(self._schema.get("required") or [])}


async def fetch_text(url: str) -> str:
    """Download a feed with a size cap; errors say what went wrong."""
    try:
        from app.integrations.web import guard_request

        async with httpx.AsyncClient(timeout=20, follow_redirects=True, event_hooks={"request": [guard_request]}) as client:
            async with client.stream("GET", url, headers={"User-Agent": "Nexus/0.2"}) as response:
                if response.status_code >= 400:
                    raise ValueError(f"Couldn't download {url}: {response.status_code}")
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_DOWNLOAD:
                        raise ValueError(f"{url} is larger than {MAX_DOWNLOAD // 1_000_000} MB")
                return body.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise ValueError(f"Couldn't download {url}: {exc}") from exc


def strip_html(text: str, limit: int = 300) -> str:
    """Readable text from a snippet of HTML (feed summaries, HTML-only emails)."""
    import html

    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

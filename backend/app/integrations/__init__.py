"""Built-in integrations: apps Nexus connects to itself, beside MCP servers (see base.py)."""
from __future__ import annotations

import logging
from typing import Any

from app.integrations import browser, calendar_feed, discord, google, mail, rss, slack, store, telegram, web
from app.integrations.base import IntegrationTool, Kind
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)

KINDS: dict[str, Kind] = {kind.id: kind for kind in (google.KIND, telegram.KIND, slack.KIND, discord.KIND, web.KIND, browser.KIND,
                                                     mail.KIND, calendar_feed.KIND, rss.KIND)}


class IntegrationManager:
    """Keeps each enabled integration's tools in the tool registry."""

    def __init__(self) -> None:
        self._tools: dict[int, list[IntegrationTool]] = {}
        self._slugs: dict[int, str] = {}
        self._runners: dict[int, Any] = {}  # running parts (Telegram bots), by integration id

    def apply(self, integration: dict[str, Any]) -> list[IntegrationTool]:
        self.remove(integration["id"])
        kind = KINDS.get(integration["kind"])
        if kind is None or not integration["enabled"]:
            return []
        # The id lets an integration save what changes while it runs (a refreshed Google token).
        config = {**kind.prepare(integration["config"]), "_integration_id": integration["id"]}
        if kind.start:  # shares ``config`` with the tools, so what it saves (a linked chat) they see too
            self._runners[integration["id"]] = kind.start(integration["id"], config)
        tools = kind.tools(integration["slug"], integration["name"], config)
        if not tools:  # e.g. Google before its sign-in finishes: not available yet
            return []
        registry = get_tool_registry()
        for tool in tools:
            registry.register(tool)
        self._tools[integration["id"]], self._slugs[integration["id"]] = tools, integration["slug"]
        return tools

    def remove(self, integration_id: int) -> None:
        registry = get_tool_registry()
        for tool in self._tools.pop(integration_id, []):
            registry.unregister(tool.tool_name)
        runner = self._runners.pop(integration_id, None)
        if runner is not None:
            runner.stop()
        self._slugs.pop(integration_id, None)

    def load_all(self) -> None:
        for integration in store.list_integrations():
            try:
                self.apply(integration)
            except Exception as exc:  # one broken integration must not stop the others
                logger.warning("Could not load integration %r: %s", integration["name"], exc)

    def runner(self, integration_id: Any) -> Any:
        return self._runners.get(integration_id)

    def runners(self) -> list[Any]:
        return list(self._runners.values())

    def tools_of(self, integration_id: int) -> list[IntegrationTool]:
        return self._tools.get(integration_id, [])

    def states(self) -> dict[str, dict[str, bool]]:
        always = {"enabled": True, "connected": True, "available": True}
        return {"web": always, "files": always, **{slug: always for slug in self._slugs.values()}}


integration_manager = IntegrationManager()
web.register_web(get_tool_registry())  # reading web pages needs no setup

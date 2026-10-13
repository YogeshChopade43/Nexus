"""Slack: chat with Nexus in a direct message, approve and answer with buttons, get reminders there.

Uses Socket Mode (Nexus opens the connection to Slack), so like Telegram it works on a home computer with no
public address. Setup is pasting the manifest below into "Create an app"; only the linked DM is served.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from typing import Any, Optional

import httpx

from app.integrations.base import Field, IntegrationTool, Kind
from app.integrations.channel import Buttons, ChatChannel, send_message_tool

logger = logging.getLogger(__name__)

API = "https://slack.com/api"
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests put a fake Slack here
CONNECT = True  # tests hand envelopes to the bot themselves
MAX_SECTION = 2900  # Slack's section block limit is 3000 characters

MANIFEST = json.dumps({
    "display_information": {"name": "Nexus", "description": "Your self-hosted Nexus assistant"},
    "features": {"bot_user": {"display_name": "Nexus", "always_online": True},
                 "app_home": {"messages_tab_enabled": True, "messages_tab_read_only_enabled": False}},
    "oauth_config": {"scopes": {"bot": ["chat:write", "im:history", "im:read", "im:write", "files:write"]}},
    "settings": {"event_subscriptions": {"bot_events": ["message.im"]}, "interactivity": {"is_enabled": True},
                 "socket_mode_enabled": True},
}, indent=2)

FIELDS = [
    Field("bot_token", "Bot token (xoxb-…)", "password",
          help="api.slack.com/apps › Create New App › From a manifest (paste the one shown here) › Install to Workspace, "
               "then OAuth & Permissions › Bot User OAuth Token."),
    Field("app_token", "App-level token (xapp-…)", "password",
          help="Basic Information › App-Level Tokens › Generate, with the connections:write scope."),
]


def to_mrkdwn(markdown: str) -> str:
    """Model Markdown in Slack's own flavour: *bold*, _italic_, <url|links>."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", markdown)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    return re.sub(r"^#{1,6} (.+)$", r"*\1*", text, flags=re.MULTILINE)


def split(text: str, limit: int = MAX_SECTION) -> list[str]:
    from app.integrations.telegram import split as cut

    return cut(text, limit)


class SlackBot(ChatChannel):
    NAME = "Slack"
    NEW_COMMANDS = ("new", "/new", "new conversation")  # "/new" alone is taken by Slack's own commands

    def __init__(self, integration_id: int, config: dict[str, Any]) -> None:
        super().__init__(integration_id, config)
        self._handling: set[asyncio.Task] = set()

    def should_connect(self) -> bool:
        return CONNECT

    async def api(self, method: str, token: Optional[str] = None, **params: Any) -> Any:
        async with httpx.AsyncClient(timeout=30, transport=TRANSPORT) as client:
            response = await client.post(f"{API}/{method}", json=params,
                                         headers={"Authorization": f"Bearer {token or self.config['bot_token']}"})
        body = response.json()
        if not body.get("ok"):
            raise ValueError(f"Slack said: {body.get('error') or response.status_code}")
        return body

    async def say(self, chat_id: Any, text: str, buttons: Optional[Buttons] = None) -> None:
        parts = split(to_mrkdwn(text or "(no reply)"))
        for index, part in enumerate(parts):
            blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": part}}]
            if buttons and index == len(parts) - 1:
                blocks.append({"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": b["text"][:75]}, "value": b["data"],
                     "action_id": f"nexus_{n}", **({"style": "primary"} if b["data"] == "approve" else {})}
                    for n, b in enumerate(b for row in buttons for b in row)]})
            await self.api("chat.postMessage", channel=chat_id, text=part, blocks=blocks)

    async def send_file(self, chat_id: Any, name: str, data: bytes) -> None:
        async with httpx.AsyncClient(timeout=60, transport=TRANSPORT) as client:
            response = await client.post(f"{API}/files.getUploadURLExternal", data={"filename": name, "length": str(len(data))},
                                         headers={"Authorization": f"Bearer {self.config['bot_token']}"})
            upload = response.json()
            if not upload.get("ok"):
                raise ValueError(f"Slack refused the file: {upload.get('error')}")
            await client.post(upload["upload_url"], content=data)
        await self.api("files.completeUploadExternal", files=[{"id": upload["file_id"], "title": name}], channel_id=chat_id)

    async def clear_buttons(self, chat_id: Any, message_ref: Any) -> None:
        if message_ref:
            await self.api("chat.update", channel=chat_id, ts=message_ref["ts"], text=message_ref["text"],
                           blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": message_ref["text"] or "…"}}])

    async def handle_envelope(self, envelope: dict[str, Any]) -> None:
        """One Socket Mode envelope: a direct message, or a button tap."""
        payload = envelope.get("payload") or {}
        if envelope.get("type") == "events_api":
            event = payload.get("event") or {}
            if event.get("type") == "message" and event.get("channel_type") == "im" and not event.get("bot_id") \
                    and not event.get("subtype"):
                await self.receive(event.get("channel"), text=event.get("text") or "")
        elif envelope.get("type") == "interactive" and payload.get("type") == "block_actions":
            action = (payload.get("actions") or [{}])[0]
            message = payload.get("message") or {}
            await self.receive((payload.get("channel") or {}).get("id"), tap=action.get("value") or "",
                               message_ref={"ts": message.get("ts"), "text": message.get("text", "")})

    async def connect(self) -> None:
        from websockets.asyncio.client import connect

        url = (await self.api("apps.connections.open", token=self.config["app_token"]))["url"]
        async with connect(url) as socket:
            async for raw in socket:
                envelope = json.loads(raw)
                if envelope.get("envelope_id"):  # acknowledge at once: Slack resends after 3 seconds
                    await socket.send(json.dumps({"envelope_id": envelope["envelope_id"]}))
                if envelope.get("type") == "disconnect":
                    return  # Slack asks for a fresh connection now and then
                task = asyncio.create_task(self.handle_envelope(envelope))
                self._handling.add(task)
                task.add_done_callback(self._handling.discard)


def prepare(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("chat_id") or config.get("pairing_code"):
        return config
    return {**config, "pairing_code": f"{secrets.randbelow(1_000_000):06d}"}


async def check(config: dict[str, Any]) -> str:
    bot = SlackBot(0, config)
    me = await bot.api("auth.test")
    await bot.api("apps.connections.open", token=config["app_token"])  # proves the app token works too
    config["bot_username"], config["team"] = me.get("user", ""), me.get("team", "")
    return f"Bot @{config['bot_username']} is ready in {config['team']}"


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    return [send_message_tool(slug, name, config, "Slack")]


def start(integration_id: int, config: dict[str, Any]) -> SlackBot:
    bot = SlackBot(integration_id, config)
    bot.start()
    return bot


KIND = Kind("slack", "Slack", "Chat with Nexus in a Slack direct message, approve with a click, and get reminders there.",
            "Hash", FIELDS, check, tools, prepare, start, extra={"manifest": MANIFEST})

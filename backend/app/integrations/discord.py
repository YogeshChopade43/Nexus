"""Discord: chat with Nexus in a direct message, approve and answer with buttons, get reminders there.

Uses the Gateway (Nexus opens the connection to Discord), so it works with no public address. Invite the bot
to a server you're in (Discord only allows DMs with bots you share a server with), then DM it the code.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any, Optional

import httpx

from app.integrations.base import Field, IntegrationTool, Kind
from app.integrations.channel import Buttons, ChatChannel, send_message_tool

logger = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests put a fake Discord here
CONNECT = True  # tests hand gateway events to the bot themselves
MAX_MESSAGE = 1900  # Discord's limit is 2000 characters
DIRECT_MESSAGES = 1 << 12  # gateway intent: DMs (their text needs no privileged intent)

FIELDS = [Field("bot_token", "Bot token", "password",
                help="discord.com/developers/applications › New Application › Bot › Reset Token, and paste it here.")]


def split(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    from app.integrations.telegram import split as cut

    return cut(text, limit)


class DiscordBot(ChatChannel):
    NAME = "Discord"

    def __init__(self, integration_id: int, config: dict[str, Any]) -> None:
        super().__init__(integration_id, config)
        self._handling: set[asyncio.Task] = set()

    def should_connect(self) -> bool:
        return CONNECT

    async def rest(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(timeout=30, transport=TRANSPORT) as client:
            response = await client.request(method, f"{API}{path}", headers={"Authorization": f"Bot {self.config['bot_token']}"}, **kwargs)
        if response.status_code >= 400:
            raise ValueError(f"Discord said: {response.text[:200] or response.status_code}")
        return response.json() if response.content else {}

    async def say(self, chat_id: Any, text: str, buttons: Optional[Buttons] = None) -> None:
        parts = split(text or "(no reply)")  # Discord shows Markdown as is
        for index, part in enumerate(parts):
            body: dict[str, Any] = {"content": part}
            if buttons and index == len(parts) - 1:
                body["components"] = [{"type": 1, "components": [
                    {"type": 2, "style": 1 if b["data"] == "approve" else 2, "label": b["text"][:80], "custom_id": b["data"]}
                    for b in row[:5]]} for row in buttons[:5]]
            await self.rest("POST", f"/channels/{chat_id}/messages", json=body)

    async def send_file(self, chat_id: Any, name: str, data: bytes) -> None:
        await self.rest("POST", f"/channels/{chat_id}/messages", data={"payload_json": json.dumps({"content": ""})},
                        files={"files[0]": (name, data)})

    async def typing(self, chat_id: Any) -> None:
        await self.rest("POST", f"/channels/{chat_id}/typing")

    async def clear_buttons(self, chat_id: Any, message_ref: Any) -> None:
        if message_ref:
            await self.rest("PATCH", f"/channels/{chat_id}/messages/{message_ref}", json={"components": []})

    async def handle_dispatch(self, event: str, data: dict[str, Any]) -> None:
        """One gateway event: a direct message, or a button tap."""
        if event == "MESSAGE_CREATE":
            if data.get("guild_id") or (data.get("author") or {}).get("bot"):
                return  # only DMs, and never our own messages
            await self.receive(data.get("channel_id"), text=data.get("content") or "")
        elif event == "INTERACTION_CREATE" and data.get("type") == 3:  # a button
            await self.rest("POST", f"/interactions/{data['id']}/{data['token']}/callback", json={"type": 6})
            await self.receive(data.get("channel_id"), tap=(data.get("data") or {}).get("custom_id") or "",
                               message_ref=(data.get("message") or {}).get("id"))

    async def connect(self) -> None:
        from websockets.asyncio.client import connect

        gateway = (await self.rest("GET", "/gateway/bot"))["url"]
        async with connect(f"{gateway}?v=10&encoding=json") as socket:
            hello = json.loads(await socket.recv())
            sequence: dict[str, Optional[int]] = {"last": None}

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(hello["d"]["heartbeat_interval"] / 1000)
                    await socket.send(json.dumps({"op": 1, "d": sequence["last"]}))

            beating = asyncio.create_task(heartbeat())
            try:
                await socket.send(json.dumps({"op": 2, "d": {"token": self.config["bot_token"], "intents": DIRECT_MESSAGES,
                                                              "properties": {"os": "linux", "browser": "nexus", "device": "nexus"}}}))
                async for raw in socket:
                    message = json.loads(raw)
                    if message.get("s") is not None:
                        sequence["last"] = message["s"]
                    if message.get("op") == 0:
                        task = asyncio.create_task(self.handle_dispatch(message.get("t"), message.get("d") or {}))
                        self._handling.add(task)
                        task.add_done_callback(self._handling.discard)
                    elif message.get("op") in (7, 9):  # Discord asks to reconnect
                        return
            finally:
                beating.cancel()


def prepare(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("chat_id") or config.get("pairing_code"):
        return config
    return {**config, "pairing_code": f"{secrets.randbelow(1_000_000):06d}"}


async def check(config: dict[str, Any]) -> str:
    app = await DiscordBot(0, config).rest("GET", "/oauth2/applications/@me")
    config["bot_username"] = (app.get("bot") or {}).get("username") or app.get("name", "")
    # Discord only lets you DM a bot you share a server with: this link adds it to one of yours.
    config["invite_url"] = f"https://discord.com/oauth2/authorize?client_id={app['id']}&scope=bot&permissions=0"
    return f"Bot @{config['bot_username']} is ready"


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    return [send_message_tool(slug, name, config, "Discord")]


def start(integration_id: int, config: dict[str, Any]) -> DiscordBot:
    bot = DiscordBot(integration_id, config)
    bot.start()
    return bot


KIND = Kind("discord", "Discord", "Chat with Nexus in a Discord direct message, approve with a click, and get reminders there.",
            "MessagesSquare", FIELDS, check, tools, prepare, start)

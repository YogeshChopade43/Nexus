"""Telegram: talk to Nexus from your phone. Answers come back as messages, approvals and question cards as
buttons, and reminders (Notify steps) arrive as notifications.

Nexus long-polls Telegram (getUpdates), so it works on a home computer with no public address. Only the one
chat linked with the pairing code is served; anyone else who finds the bot is turned away.
"""
from __future__ import annotations

import html
import logging
import re
import secrets
from typing import Any, Optional

import httpx

from app.integrations.base import Field, IntegrationTool, Kind
from app.integrations.channel import Buttons, ChatChannel, linked_channels, send_message_tool

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests put a fake Telegram here
POLLING = True  # tests hand updates to the bot themselves
LONG_POLL = 25  # seconds Telegram holds a getUpdates call open
MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters

FIELDS = [Field("bot_token", "Bot token", "password",
                help="In Telegram, message @BotFather, send /newbot, pick a name, and paste the token it gives you.")]


# ---- formatting -----------------------------------------------------------------------------------

def to_html(markdown: str) -> str:
    """The Markdown models write, as the small HTML subset Telegram shows (bold, italics, code, links)."""
    blocks = []

    def keep(match: re.Match) -> str:
        blocks.append(f"<pre>{html.escape(match.group(1))}</pre>")
        return f"\x00{len(blocks) - 1}\x00"

    text = re.sub(r"```[^\n]*\n(.*?)```", keep, markdown, flags=re.DOTALL)
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"^#{1,6} (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    return re.sub(r"\x00(\d+)\x00", lambda m: blocks[int(m.group(1))], text)


def split(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Long replies as several messages, cut at line breaks or spaces where possible."""
    parts = []
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut])
        text = text[cut:]
    return parts + ([text] if text else [])


# ---- the bot ----------------------------------------------------------------------------------------

class Bot(ChatChannel):
    NAME = "Telegram"

    def __init__(self, integration_id: int, config: dict[str, Any]) -> None:
        super().__init__(integration_id, config)
        self.offset = 0

    def should_connect(self) -> bool:
        return POLLING

    async def api(self, method: str, **params: Any) -> Any:
        async with httpx.AsyncClient(timeout=LONG_POLL + 10, transport=TRANSPORT) as client:
            response = await client.post(f"{API}/bot{self.config['bot_token']}/{method}", json=params)
        body = response.json()
        if not body.get("ok"):
            raise ValueError(f"Telegram said: {body.get('description') or response.status_code}")
        return body["result"]

    async def say(self, chat_id: Any, text: str, buttons: Optional[Buttons] = None) -> None:
        keyboard = [[{"text": b["text"], "callback_data": b["data"]} for b in row] for row in buttons or []]
        parts = split(text or "(no reply)")
        for index, part in enumerate(parts):
            extra = {"reply_markup": {"inline_keyboard": keyboard}} if keyboard and index == len(parts) - 1 else {}
            try:
                await self.api("sendMessage", chat_id=chat_id, text=to_html(part), parse_mode="HTML", **extra)
            except ValueError:  # Telegram couldn't parse the HTML: send it plain
                await self.api("sendMessage", chat_id=chat_id, text=part, **extra)

    async def send_file(self, chat_id: Any, name: str, data: bytes) -> None:
        async with httpx.AsyncClient(timeout=60, transport=TRANSPORT) as client:
            response = await client.post(f"{API}/bot{self.config['bot_token']}/sendDocument",
                                         data={"chat_id": str(chat_id)}, files={"document": (name, data)})
        if not response.json().get("ok"):
            raise ValueError(f"Telegram didn't take the file: {response.json().get('description')}")

    async def typing(self, chat_id: Any) -> None:
        await self.api("sendChatAction", chat_id=chat_id, action="typing")

    async def clear_buttons(self, chat_id: Any, message_ref: Any) -> None:
        if message_ref is not None:
            await self.api("editMessageReplyMarkup", chat_id=chat_id, message_id=message_ref, reply_markup={"inline_keyboard": []})

    async def handle(self, update: dict[str, Any]) -> None:
        """One Telegram update: a message or a button tap."""
        message, callback = update.get("message"), update.get("callback_query")
        if callback:
            chat_id = callback.get("message", {}).get("chat", {}).get("id")
            if chat_id == self.config.get("chat_id"):
                await self.api("answerCallbackQuery", callback_query_id=callback["id"])
            await self.receive(chat_id, tap=callback.get("data") or "", message_ref=callback.get("message", {}).get("message_id"))
        elif message and message.get("text"):
            await self.receive(message.get("chat", {}).get("id"), text=message["text"])

    async def connect(self) -> None:
        while True:
            updates = await self.api("getUpdates", offset=self.offset, timeout=LONG_POLL,
                                     allowed_updates=["message", "callback_query"])
            for update in updates:
                self.offset = update["update_id"] + 1
                await self.handle(update)


# ---- the integration ---------------------------------------------------------------------------------

def prepare(config: dict[str, Any]) -> dict[str, Any]:
    """A pairing code until a chat is linked: whoever sends it to the bot becomes its one user."""
    if config.get("chat_id") or config.get("pairing_code"):
        return config
    return {**config, "pairing_code": f"{secrets.randbelow(1_000_000):06d}"}


async def check(config: dict[str, Any]) -> str:
    me = await Bot(0, config).api("getMe")
    config["bot_username"] = me.get("username", "")  # saved with the integration: the UI links to the bot
    return f"Bot @{config['bot_username']} is ready"


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    return [send_message_tool(slug, name, config, "Telegram")]


async def notify_all(title: str, message: str = "") -> None:
    """Forward a Notify step (reminders, alerts) to every linked chat: Telegram, Slack or Discord."""
    for channel in linked_channels():
        try:
            await channel.say(channel.config["chat_id"], f"🔔 **{title}**" + (f"\n{message}" if message else ""))
        except Exception as exc:  # the bell still has it
            logger.warning("Couldn't send a reminder to %s: %s", channel.NAME, exc)


def start(integration_id: int, config: dict[str, Any]) -> Bot:
    bot = Bot(integration_id, config)
    bot.start()
    return bot


KIND = Kind("telegram", "Telegram", "Chat with Nexus from your phone, approve actions with a tap, and get reminders there.",
            "Send", FIELDS, check, tools, prepare, start)

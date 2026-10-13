"""What every chat channel (Telegram, Slack, Discord) does the same way: link one private chat with a pairing
code, run each message through the Nexus agent, turn approvals and question cards into buttons, and send the
files a reply made. Each platform only says how to send, show buttons, upload a file and stay connected.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.integrations import store

logger = logging.getLogger(__name__)

Buttons = list[list[dict[str, str]]]  # rows of {"text": label, "data": what tapping sends back}


def readable(tool: str) -> str:
    app, _, action = tool.partition("__")
    return f"{app.replace('_', ' ').title()} › {action.replace('_', ' ')}" if action else tool


def files_made(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Files a reply made (Create file); a tool's own data sits under the result's ``data``."""
    found = []
    for event in events or []:
        result = event.get("data") if isinstance(event.get("data"), dict) else {}
        made = (result.get("data") or {}).get("file") if isinstance(result.get("data"), dict) else None
        if event.get("type") == "tool_executed" and made:
            found.append(made)
    return found


class ChatChannel:
    NAME = "Chat"
    NEW_COMMANDS = ("/new", "/start", "new conversation")

    def __init__(self, integration_id: int, config: dict[str, Any]) -> None:
        self.integration_id = integration_id
        self.config = config
        self.task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.lock = asyncio.Lock()
        self.questions: list[dict[str, Any]] = []  # an open question card, asked one question at a time
        self.answers: dict[str, Any] = {}

    # -- what each platform provides --
    async def say(self, chat_id: Any, text: str, buttons: Optional[Buttons] = None) -> None:
        raise NotImplementedError

    async def send_file(self, chat_id: Any, name: str, data: bytes) -> None:
        raise NotImplementedError

    async def typing(self, chat_id: Any) -> None:  # optional
        pass

    async def clear_buttons(self, chat_id: Any, message_ref: Any) -> None:  # optional: after a tap
        pass

    async def connect(self) -> None:
        """Stay connected and feed messages to ``receive``; returns or raises when the connection drops."""
        raise NotImplementedError

    def should_connect(self) -> bool:
        return True

    # -- shared --
    def _save(self, **changes: Any) -> None:
        self.config.update(changes)
        saved = store.get_integration(self.integration_id)
        if saved:
            store.update_integration(self.integration_id, config={**saved["config"], **changes})

    async def receive(self, chat_id: Any, text: str = "", tap: Optional[str] = None, message_ref: Any = None) -> None:
        """A message (``text``) or a button tap (``tap``) from ``chat_id``."""
        async with self.lock:  # one at a time: answers must follow their questions
            if chat_id != self.config.get("chat_id"):
                await self._stranger(chat_id, text.strip())
                return
            try:
                if tap is not None:
                    await self.clear_buttons(chat_id, message_ref)
                    await self._tapped(chat_id, tap)
                elif text.strip():
                    await self._message(chat_id, text.strip())
            except Exception as exc:  # tell the user instead of going quiet
                logger.warning("%s message failed: %s", self.NAME, exc)
                await self.say(chat_id, f"Something went wrong: {getattr(exc, 'detail', None) or exc}")

    async def _stranger(self, chat_id: Any, text: str) -> None:
        code = self.config.get("pairing_code")
        if not self.config.get("chat_id") and code and text in (f"/start {code}", f"link {code}", code):
            from app.agent.sessions import create_session

            self._save(chat_id=chat_id, session_id=create_session(title=self.NAME))
            await self.say(chat_id, "Linked to Nexus. Message me anything, like you would in the Nexus chat. "
                                    f"Reminders will arrive here too. Send {self.NEW_COMMANDS[0]} to start a fresh conversation.")
            return
        await self.say(chat_id, "This is a private Nexus bot. To link it, use the link or code shown in Nexus.")

    async def _message(self, chat_id: Any, text: str) -> None:
        if text.lower() in self.NEW_COMMANDS:
            from app.agent.sessions import create_session

            self._save(session_id=create_session(title=self.NAME))
            self.questions, self.answers = [], {}
            await self.say(chat_id, "Started a new conversation.")
            return
        if self.questions:  # typing answers the open question in your own words
            await self._answer(chat_id, text)
            return
        from app.api.routes.agent import run_agent
        from app.models.agent import AgentRunRequest

        await self.typing(chat_id)
        await self._reply(chat_id, await run_agent(AgentRunRequest(message=text, session_id=self.config.get("session_id"))))

    async def _tapped(self, chat_id: Any, data: str) -> None:
        if data in ("approve", "deny"):
            from app.api.routes.agent import answer_approval
            from app.models.agent import ApprovalRequest

            await self.typing(chat_id)
            await self._reply(chat_id, await answer_approval(self.config["session_id"], ApprovalRequest(approved=data == "approve")))
        elif data.startswith("ans:") and self.questions:
            index, choice = (int(x) for x in data.split(":")[1:])
            question = self.questions[len(self.answers)]
            if index == len(self.answers) and 0 <= choice < len(question.get("options") or []):
                await self._answer(chat_id, question["options"][choice]["label"])

    async def _answer(self, chat_id: Any, answer: str) -> None:
        self.answers[self.questions[len(self.answers)]["question"]] = answer
        if len(self.answers) < len(self.questions):
            await self._ask(chat_id)
            return
        from app.api.routes.agent import answer_questions
        from app.models.agent import AnswerRequest

        answers, self.questions, self.answers = self.answers, [], {}
        await self.typing(chat_id)
        await self._reply(chat_id, await answer_questions(self.config["session_id"], AnswerRequest(answers=answers)))

    async def _ask(self, chat_id: Any) -> None:
        index = len(self.answers)
        question = self.questions[index]
        buttons = [[{"text": option["label"], "data": f"ans:{index}:{j}"}] for j, option in enumerate(question.get("options") or [])]
        await self.say(chat_id, f"{question['question']}\n\n_Tap an option, or type your own answer._", buttons)

    async def _reply(self, chat_id: Any, result: Any) -> None:
        if result.status == "needs_approval" and result.pending_action:
            action = result.pending_action
            details = "\n".join(f"• {key}: {str(value)[:200]}" for key, value in list((action.get("arguments") or {}).items())[:8])
            await self.say(chat_id, f"Nexus wants to use **{readable(action['tool'])}**\n{details}".strip(),
                           [[{"text": "Approve", "data": "approve"}, {"text": "Deny", "data": "deny"}]])
        elif result.status == "needs_input" and result.pending_question:
            self.questions, self.answers = list(result.pending_question.get("questions") or []), {}
            await self._ask(chat_id)
        else:
            await self.say(chat_id, result.response or result.message)
            from app.files import attachments

            for made in files_made(result.events):  # e.g. an export the agent made
                for name, data in attachments(made["id"]):
                    await self.send_file(chat_id, name, data)

    # -- running --
    async def _keep_connected(self) -> None:
        delay = 5
        while True:
            try:
                await self.connect()
                delay = 5
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # offline, or the platform hiccuped: back off and reconnect
                logger.info("%s connection paused: %s", self.NAME, exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)

    def start(self) -> None:
        if not self.should_connect():
            return
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop here (a worker thread): the next start, at app startup, connects
        self.task = self.loop.create_task(self._keep_connected())

    def stop(self) -> None:
        if self.task and self.loop:
            self.loop.call_soon_threadsafe(self.task.cancel)


def linked_channels() -> list[ChatChannel]:
    from app.integrations import integration_manager

    return [r for r in integration_manager.runners() if isinstance(r, ChatChannel) and r.config.get("chat_id")]


def channel_for(config: dict[str, Any]) -> Optional[ChatChannel]:
    from app.integrations import integration_manager

    runner = integration_manager.runner(config.get("_integration_id"))
    return runner if isinstance(runner, ChatChannel) else None


def send_message_tool(slug: str, name: str, config: dict[str, Any], platform: str) -> Any:
    """The "send the user a message" tool every channel offers to workflows."""
    from app.integrations.base import IntegrationTool

    async def send(p: dict[str, Any]) -> Any:
        channel = channel_for(config)
        if not channel or not channel.config.get("chat_id"):
            raise ValueError(f"{platform} isn't linked yet: send the bot the code shown in Nexus (/start <code>)")
        await channel.say(channel.config["chat_id"], str(p.get("text") or ""))
        return f"Sent to {platform}."

    return IntegrationTool(slug, name, "send_message", f"Send the user a {platform} message (Markdown allowed): "
                           "alerts, reminders, summaries.", {
                               "properties": {"text": {"type": "string"}}, "required": ["text"]},
                           send, title=f"Send {platform} message")

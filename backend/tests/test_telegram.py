"""Telegram: chat with Nexus from your phone, tap to approve or answer, get reminders there."""
from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import integration_manager, store, telegram
from app.main import app
from app.tools import get_tool_registry
from tests.test_chatbot import FIXTURE, ScriptedLLM

SENT: list[dict] = []


def fake_telegram(request: httpx.Request) -> httpx.Response:
    method = request.url.path.rsplit("/", 1)[1]
    assert "/bot123:secret/" in request.url.path
    multipart = request.headers.get("content-type", "").startswith("multipart/")
    body = {"file": request.content} if multipart else json.loads(request.content or b"{}")
    if method == "getMe":
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "nexus_test_bot", "is_bot": True}})
    if method in ("sendMessage", "editMessageReplyMarkup", "answerCallbackQuery", "sendChatAction", "sendDocument"):
        SENT.append({"method": method, **body})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(SENT)}})
    return httpx.Response(200, json={"ok": True, "result": []})


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(telegram, "TRANSPORT", httpx.MockTransport(fake_telegram))
    monkeypatch.setattr(telegram, "POLLING", False)  # tests hand updates to the bot directly
    SENT.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        echo = c.post("/api/mcp/servers", json={"name": "Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE],
                                                 "tool_policies": {"echo": "ask"}}).json()
        c.echo_tool = f"{echo['slug']}__echo"  # the slug may be echo_2 if another test made an "Echo" first
        yield c
        c.delete(f"/api/mcp/servers/{echo['id']}")


@pytest.fixture
def llm(monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    fake = ScriptedLLM()
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "m"}), {}))
    return fake


def message(chat: int, text: str) -> dict:
    return {"update_id": 1, "message": {"message_id": 5, "chat": {"id": chat, "type": "private"}, "text": text}}


def tap(chat: int, data: str) -> dict:
    return {"update_id": 2, "callback_query": {"id": "cb1", "data": data,
                                               "message": {"message_id": 9, "chat": {"id": chat}}}}


def texts() -> list[str]:
    return [m["text"] for m in SENT if m["method"] == "sendMessage"]


@pytest.fixture
def bot(client):
    created = client.post("/api/integrations", json={"kind": "telegram", "name": "Telegram", "config": {"bot_token": "123:secret"}})
    assert created.status_code == 200, created.text
    item = created.json()
    yield item, integration_manager.runner(item["id"])
    client.delete(f"/api/integrations/{item['id']}")


def link(client, item, runner):
    code = item["settings"]["pairing_code"]
    client.portal.call(runner.handle, message(42, f"/start {code}"))


def test_connecting_checks_the_token_and_shows_how_to_link(bot):
    item, _ = bot
    assert "@nexus_test_bot" in item["message"] and item["status"] == "needs_auth"
    assert item["settings"]["bot_username"] == "nexus_test_bot" and len(item["settings"]["pairing_code"]) == 6
    assert "bot_token" not in str(item)


def test_only_the_linked_chat_is_served(client, bot):
    item, runner = bot
    client.portal.call(runner.handle, message(7, "hello"))
    assert "private" in texts()[-1].lower()
    client.portal.call(runner.handle, message(7, "/start 000000"))
    assert store.get_integration(item["id"])["config"].get("chat_id") is None
    link(client, item, runner)
    assert store.get_integration(item["id"])["config"]["chat_id"] == 42 and "Linked" in texts()[-1]
    client.portal.call(runner.handle, (message(7, "hello again")))  # someone else, after linking
    assert "private" in texts()[-1].lower()


def test_chatting_from_telegram(client, bot, llm):
    item, runner = bot
    link(client, item, runner)
    llm.script = lambda m, t: {"content": "**Hi** there, `Yogesh`", "tool_calls": []}
    client.portal.call(runner.handle, message(42, "hello"))
    reply = SENT[-1]
    assert reply["text"] == "<b>Hi</b> there, <code>Yogesh</code>" and reply["parse_mode"] == "HTML"


def test_approvals_are_buttons(client, bot, llm):
    item, runner = bot
    link(client, item, runner)
    llm.script = lambda m, t: ({"content": "Echoed it.", "tool_calls": []} if m[-1]["role"] == "tool"
                               else (client.echo_tool, {"text": "ping"}))
    client.portal.call(runner.handle, message(42, "echo the text ping"))
    ask = SENT[-1]
    assert "Echo" in ask["text"] and "ping" in ask["text"]
    buttons = [b["callback_data"] for row in ask["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == ["approve", "deny"]
    client.portal.call(runner.handle, tap(42, "approve"))
    assert texts()[-1] == "Echoed it."


def test_question_cards_are_buttons_or_typed_answers(client, bot, llm):
    item, runner = bot
    link(client, item, runner)
    question = {"questions": [{"question": "Where should the alert go?", "header": "Alerts",
                               "options": [{"label": "Nexus pop-up"}, {"label": "Telegram"}]}]}
    llm.script = lambda m, t: ({"content": "Got it: " + m[-1]["content"], "tool_calls": []} if m[-1]["role"] == "tool"
                               else ("nexus_ask_user", question))
    client.portal.call(runner.handle, message(42, "echo a reminder for me"))
    card = SENT[-1]
    assert card["text"].startswith("Where should the alert go?")
    assert [b["text"] for row in card["reply_markup"]["inline_keyboard"] for b in row] == ["Nexus pop-up", "Telegram"]
    client.portal.call(runner.handle, tap(42, "ans:0:1"))
    assert "Telegram" in texts()[-1]

    client.portal.call(runner.handle, message(42, "echo another reminder"))
    client.portal.call(runner.handle, (message(42, "By email please")))  # typing answers the open question
    assert "By email please" in texts()[-1]


def test_reminders_reach_the_phone(client, bot):
    item, runner = bot
    link(client, item, runner)
    from app.auth.owner import as_user

    with as_user(client.get("/api/auth/me").json()["id"]):  # a reminder runs as its owner (a workflow or chat)
        client.portal.call(get_tool_registry().get_tool("nexus__notify").execute, {"title": "Take your medicines", "message": "2 tablets"})
    assert "Take your medicines" in texts()[-1] and "2 tablets" in texts()[-1]


def test_send_message_tool_for_workflows(client, bot):
    item, runner = bot
    tool = f"{item['slug']}__send_message"
    with pytest.raises(ValueError, match="/start"):
        client.portal.call(get_tool_registry().get_tool(tool).execute, {"text": "hi"})  # not linked yet
    link(client, item, runner)
    client.portal.call(get_tool_registry().get_tool(tool).execute, {"text": "Build passed"})
    assert SENT[-1]["chat_id"] == 42 and SENT[-1]["text"] == "Build passed"


def test_markdown_becomes_telegram_html_and_long_replies_are_split():
    assert telegram.to_html("a < b & **c** [x](https://e.com)") == 'a &lt; b &amp; <b>c</b> <a href="https://e.com">x</a>'
    assert telegram.to_html("```py\nprint(1)\n```") == "<pre>print(1)\n</pre>"
    parts = telegram.split("word " * 2000)
    assert all(len(p) <= 4000 for p in parts) and "".join(parts).split() == ["word"] * 2000


def test_files_made_in_a_reply_arrive_as_documents(client, bot, llm):
    item, runner = bot
    link(client, item, runner)
    llm.script = lambda m, t: ({"content": "Here's your export.", "tool_calls": []} if m[-1]["role"] == "tool"
                               else ("files__create_file", {"filename": "issues.csv", "content": "title\nLogin bug"}))
    client.portal.call(runner.handle, message(42, "export the issues to a csv file"))
    documents = [m for m in SENT if m["method"] == "sendDocument"]
    assert documents and b"issues.csv" in documents[0]["file"] and b"Login bug" in documents[0]["file"]
    assert texts()[-1] == "Here's your export."

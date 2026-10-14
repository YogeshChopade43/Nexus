"""Slack (Socket Mode) and Discord (Gateway) bots: the same chat, approvals, questions and files as Telegram."""
from __future__ import annotations

import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import discord, integration_manager, slack, store
from app.main import app
from tests.test_chatbot import FIXTURE, ScriptedLLM

CALLS: list[dict] = []


def fake_slack(request: httpx.Request) -> httpx.Response:
    method = request.url.path.rsplit("/", 1)[-1]
    body = json.loads(request.content) if request.headers.get("content-type", "").startswith("application/json") else {}
    CALLS.append({"platform": "slack", "method": method, "auth": request.headers.get("authorization"), "body": body,
                  "raw": request.content})
    if request.url.host == "files.example":  # the upload URL Slack hands out
        return httpx.Response(200, text="OK")
    replies = {
        "auth.test": {"ok": True, "user": "nexus", "team": "Acme", "user_id": "U0BOT"},
        "apps.connections.open": {"ok": True, "url": "wss://socket.example/ws"},
        "files.getUploadURLExternal": {"ok": True, "upload_url": "https://files.example/upload", "file_id": "F1"},
    }
    return httpx.Response(200, json=replies.get(method, {"ok": True}))


def fake_discord(request: httpx.Request) -> httpx.Response:
    path = request.url.path.replace("/api/v10", "")
    multipart = request.headers.get("content-type", "").startswith("multipart/")
    body = {} if multipart or not request.content else json.loads(request.content)
    CALLS.append({"platform": "discord", "method": f"{request.method} {path}", "auth": request.headers.get("authorization"),
                  "body": body, "raw": request.content if multipart else b""})
    if path == "/oauth2/applications/@me":
        return httpx.Response(200, json={"id": "1234", "name": "Nexus", "bot": {"username": "nexus"}})
    return httpx.Response(200, json={"id": "m1"})


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(slack, "TRANSPORT", httpx.MockTransport(fake_slack))
    monkeypatch.setattr(discord, "TRANSPORT", httpx.MockTransport(fake_discord))
    monkeypatch.setattr(slack, "CONNECT", False)
    monkeypatch.setattr(discord, "CONNECT", False)
    CALLS.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        echo = c.post("/api/mcp/servers", json={"name": "Chan Echo", "transport": "stdio", "command": sys.executable,
                                                 "args": [FIXTURE], "tool_policies": {"echo": "ask"}}).json()
        c.echo_tool = f"{echo['slug']}__echo"
        yield c
        c.delete(f"/api/mcp/servers/{echo['id']}")


@pytest.fixture
def llm(monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    fake = ScriptedLLM()
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "m"}), {}))
    return fake


def connect(client, kind, config):
    created = client.post("/api/integrations", json={"kind": kind, "name": kind.title(), "config": config})
    assert created.status_code == 200, created.text
    item = created.json()
    return item, integration_manager.runner(item["id"])


# ---- Slack ----------------------------------------------------------------------------------------

def slack_message(channel, text):
    return {"type": "events_api", "envelope_id": "e1", "payload": {"event": {
        "type": "message", "channel": channel, "channel_type": "im", "user": "U1", "text": text}}}


def slack_tap(channel, value):
    return {"type": "interactive", "envelope_id": "e2", "payload": {
        "type": "block_actions", "channel": {"id": channel}, "message": {"ts": "1.1", "text": "Nexus wants to use…"},
        "actions": [{"value": value}]}}


def slack_posts():
    return [c["body"] for c in CALLS if c["platform"] == "slack" and c["method"] == "chat.postMessage"]


def test_slack_setup_link_chat_and_approve(client, llm):
    item, bot = connect(client, "slack", {"bot_token": "xoxb-1", "app_token": "xapp-1"})
    assert "@nexus" in item["message"] and "Acme" in item["message"] and item["status"] == "needs_auth"
    assert {c["auth"] for c in CALLS if c["method"] == "apps.connections.open"} == {"Bearer xapp-1"}
    kinds = {k["id"]: k for k in client.get("/api/integrations/kinds").json()}
    assert '"socket_mode_enabled": true' in kinds["slack"]["manifest"]

    client.portal.call(bot.handle_envelope, slack_message("D9", "hello"))
    assert "private" in slack_posts()[-1]["text"].lower()
    client.portal.call(bot.handle_envelope, slack_message("D1", item["settings"]["pairing_code"]))
    assert store.get_integration(item["id"])["config"]["chat_id"] == "D1" and "Linked" in slack_posts()[-1]["text"]

    llm.script = lambda m, t: {"content": "**Done** — see [docs](https://ex.com)", "tool_calls": []}
    client.portal.call(bot.handle_envelope, slack_message("D1", "hi there"))
    assert slack_posts()[-1]["text"] == "*Done* — see <https://ex.com|docs>"  # Slack's own formatting

    llm.script = lambda m, t: ({"content": "Echoed.", "tool_calls": []} if m[-1]["role"] == "tool"
                               else (client.echo_tool, {"text": "ping"}))
    client.portal.call(bot.handle_envelope, slack_message("D1", "echo the text ping"))
    actions = next(b for b in slack_posts()[-1]["blocks"] if b["type"] == "actions")
    assert [e["value"] for e in actions["elements"]] == ["approve", "deny"]
    client.portal.call(bot.handle_envelope, slack_tap("D1", "approve"))
    assert slack_posts()[-1]["text"] == "Echoed."
    assert any(c["method"] == "chat.update" for c in CALLS)  # the buttons go away once tapped
    client.delete(f"/api/integrations/{item['id']}")


def test_slack_files_upload(client, llm):
    item, bot = connect(client, "slack", {"bot_token": "xoxb-1", "app_token": "xapp-1"})
    client.portal.call(bot.handle_envelope, slack_message("D1", item["settings"]["pairing_code"]))
    llm.script = lambda m, t: ({"content": "Here you go.", "tool_calls": []} if m[-1]["role"] == "tool"
                               else ("files__create_file", {"filename": "list.csv", "content": "a\n1"}))
    client.portal.call(bot.handle_envelope, slack_message("D1", "export a csv file"))
    methods = [c["method"] for c in CALLS if c["platform"] == "slack"]
    assert "files.getUploadURLExternal" in methods and "files.completeUploadExternal" in methods
    complete = next(c for c in CALLS if c["method"] == "files.completeUploadExternal")
    assert complete["body"]["channel_id"] == "D1" and complete["body"]["files"][0]["id"] == "F1"
    client.delete(f"/api/integrations/{item['id']}")


# ---- Discord --------------------------------------------------------------------------------------

def dm(channel, text, bot=False):
    return "MESSAGE_CREATE", {"channel_id": channel, "content": text, "author": {"id": "u1", "bot": bot}}


def discord_posts():
    return [c["body"] for c in CALLS if c["platform"] == "discord" and c["method"].startswith("POST /channels/") and c["method"].endswith("/messages")]


def test_discord_setup_link_chat_and_approve(client, llm):
    item, bot = connect(client, "discord", {"bot_token": "dtoken"})
    assert item["status"] == "needs_auth" and item["settings"]["invite_url"].startswith("https://discord.com/oauth2/authorize?client_id=1234")
    assert {c["auth"] for c in CALLS} == {"Bot dtoken"}

    client.portal.call(bot.handle_dispatch, *dm("C9", "hello"))
    assert "private" in discord_posts()[-1]["content"].lower()
    client.portal.call(bot.handle_dispatch, *dm("C1", f"link {item['settings']['pairing_code']}"))
    assert store.get_integration(item["id"])["config"]["chat_id"] == "C1"
    posted = len(discord_posts())
    client.portal.call(bot.handle_dispatch, *dm("C1", "ignore me", bot=True))  # the bot's own messages
    assert len(discord_posts()) == posted

    llm.script = lambda m, t: ({"content": "Echoed.", "tool_calls": []} if m[-1]["role"] == "tool"
                               else (client.echo_tool, {"text": "ping"}))
    client.portal.call(bot.handle_dispatch, *dm("C1", "echo the text ping"))
    buttons = discord_posts()[-1]["components"][0]["components"]
    assert [b["custom_id"] for b in buttons] == ["approve", "deny"]
    client.portal.call(bot.handle_dispatch, "INTERACTION_CREATE", {
        "id": "i1", "token": "tok", "type": 3, "channel_id": "C1", "data": {"custom_id": "approve"}, "message": {"id": "m7"}})
    assert any(c["method"] == "POST /interactions/i1/tok/callback" for c in CALLS)
    assert discord_posts()[-1]["content"] == "Echoed."
    client.delete(f"/api/integrations/{item['id']}")


def test_long_discord_replies_are_split():
    assert all(len(p) <= 2000 for p in discord.split("x " * 3000))


def test_guessing_the_pairing_code_locks_linking_until_a_new_code(client, llm):
    """A 6-digit code with unlimited tries can be guessed; after 10 wrong ones, linking stops until you ask for a new code."""
    item, bot = connect(client, "discord", {"bot_token": "dtoken"})
    code = item["settings"]["pairing_code"]
    for n in range(10):
        client.portal.call(bot.handle_dispatch, *dm("C9", f"link {(int(code) + 1 + n) % 1_000_000:06d}"))
    client.portal.call(bot.handle_dispatch, *dm("C9", f"link {code}"))  # even the right one, now
    assert store.get_integration(item["id"])["config"].get("chat_id") is None
    assert "locked" in discord_posts()[-1]["content"].lower()
    assert client.get("/api/integrations").json()[-1]["settings"]["pairing_locked"] is True

    fresh = client.post(f"/api/integrations/{item['id']}/pairing-code")
    assert fresh.status_code == 200, fresh.text
    settings = fresh.json()["settings"]
    assert settings["pairing_code"] != code and not settings.get("pairing_locked")
    bot = integration_manager.runner(item["id"])
    client.portal.call(bot.handle_dispatch, *dm("C1", settings["pairing_code"]))
    assert store.get_integration(item["id"])["config"]["chat_id"] == "C1"
    client.delete(f"/api/integrations/{item['id']}")


def test_bots_act_for_whoever_connected_them_and_reminders_stay_theirs(client, llm):
    """Ana's bot works as Ana (her chats), and her reminders reach her chat app, never Bo's."""
    from app.auth.owner import as_user
    from app.integrations.telegram import notify_all

    ana_item, ana_bot = connect(client, "discord", {"bot_token": "dtoken"})
    client.portal.call(ana_bot.handle_dispatch, *dm("A1", ana_item["settings"]["pairing_code"]))
    with TestClient(app, user="bo@example.com") as bo:
        bo_item = bo.post("/api/integrations", json={"kind": "discord", "name": "Bo's Discord", "config": {"bot_token": "dtoken"}}).json()
        bo_bot = integration_manager.runner(bo_item["id"])
        client.portal.call(bo_bot.handle_dispatch, *dm("B1", bo_item["settings"]["pairing_code"]))

        # Ana's linked chat is a chat of Ana's (Bo can't see it).
        ana_chat = store.get_integration(ana_item["id"])["config"]["session_id"]
        assert bo.get(f"/api/agent/sessions/{ana_chat}").status_code == 404
        assert client.get(f"/api/agent/sessions/{ana_chat}").status_code == 200

        CALLS.clear()
        ana_id = client.get("/api/auth/me").json()["id"]
        with as_user(ana_id):
            client.portal.call(notify_all, "Ana's pills", "")
        sent_to = {c["method"] for c in CALLS if c["method"].startswith("POST /channels/")}
        assert sent_to == {"POST /channels/A1/messages"}  # not B1
        bo.delete(f"/api/integrations/{bo_item['id']}")
    client.delete(f"/api/integrations/{ana_item['id']}")

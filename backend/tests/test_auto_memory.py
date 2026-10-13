"""Nexus learns lasting facts from chats by itself (every few messages, in the background), visibly and editably."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import knowledge
from app.main import app
from tests.test_chatbot import ScriptedLLM


class Learner(ScriptedLLM):
    """Answers chat turns plainly; the memory extraction call gets ``facts``."""

    def __init__(self, facts):
        super().__init__(lambda m, t: {"content": "ok", "tool_calls": []})
        self.facts = facts
        self.extractions = 0

    async def chat(self, messages, **kwargs):
        if "facts worth remembering" in messages[-1]["content"]:
            self.extractions += 1
            self.seen = messages[-1]["content"]
            return {"content": json.dumps(self.facts), "usage": {"input_tokens": 50, "output_tokens": 10}}
        return await super().chat(messages, **kwargs)

    async def chat_stream(self, messages, **kwargs):
        yield "ok"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def learner(monkeypatch):
    import app.api.routes.agent as agent_route
    from app.llm.metering import Metered

    holder = {}

    def use(facts):
        holder["llm"] = Learner(facts)
        monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(holder["llm"], None, {"model": "m"}), {}))
        return holder["llm"]

    for memory in knowledge.list_memories():
        knowledge.delete_memory(memory["id"])
    yield use


def chat(client, sid, text):
    client.post("/api/agent/run", json={"message": text, "session_id": sid})


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_every_third_message_learns_new_facts(client, learner):
    llm = learner(["My GitHub username is YogeshChopade43", "Reminders should go to Telegram"])
    sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
    chat(client, sid, "list my repos")
    chat(client, sid, "my github is YogeshChopade43")
    assert llm.extractions == 0  # not every message: it costs tokens
    chat(client, sid, "and send reminders to telegram please")
    assert wait_for(lambda: len(knowledge.list_memories()) == 2)
    learned = knowledge.list_memories()
    assert {m["source"] for m in learned} == {"auto"}
    assert "YogeshChopade43" in llm.seen and "send reminders to telegram" in llm.seen
    activity = client.get("/api/activity", params={"limit": 10}).json()
    rows = activity if isinstance(activity, list) else activity["activities"]
    assert any(a["type"] == "memory_learned" and "Telegram" in a["title"] for a in rows)


def test_known_facts_are_not_repeated_and_nothing_is_fine(client, learner):
    knowledge.add_memory("My GitHub username is YogeshChopade43")
    llm = learner(["my github username is yogeshchopade43"])
    sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
    for text in ("a", "b", "c"):
        chat(client, sid, text)
    assert wait_for(lambda: llm.extractions == 1)
    assert "YogeshChopade43" in llm.seen  # the model sees what's already known
    time.sleep(0.2)
    assert len(knowledge.list_memories()) == 1


def test_it_can_be_switched_off(client, learner):
    client.patch("/api/settings/user", json={"memory": {"auto": False}})
    try:
        llm = learner(["Something"])
        sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
        for text in ("a", "b", "c"):
            chat(client, sid, text)
        time.sleep(0.3)
        assert llm.extractions == 0 and knowledge.list_memories() == []
    finally:
        client.patch("/api/settings/user", json={"memory": {"auto": True}})

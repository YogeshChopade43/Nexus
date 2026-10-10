"""Question cards: the agent pauses to ask the user (nexus_ask_user), then continues with the answers."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent.abstract import ASK_USER
from app.llm.metering import Metered
from app.main import app
from tests.test_chatbot import ScriptedLLM

QUESTION = {"question": "Where should the reminder reach you?", "header": "Alerts", "multi_select": False,
            "options": [{"label": "Nexus pop-up", "description": "Shows in Nexus while it's open"},
                        {"label": "Slack", "description": "A message in a channel"}]}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def llm(monkeypatch):
    fake = ScriptedLLM()
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "fake-model"}), {}))
    return fake


def session(client):
    sid = client.post("/api/agent/sessions", json={}).json()["session_id"]
    client.put(f"/api/agent/sessions/{sid}/settings", json={"servers": [], "instructions": "", "temperature": None})
    return sid


def asks_then_answers(messages, tools):
    last = messages[-1]
    if last["role"] == "tool":
        return {"content": f"Got it: {last['content']}", "tool_calls": []}
    return (ASK_USER, {"questions": [QUESTION]})


def test_the_reply_pauses_with_the_question_and_continues_with_the_answer(client, llm):
    llm.script = asks_then_answers
    sid = session(client)
    asked = client.post("/api/agent/run", json={"message": "Remind me to take meds daily at 1 pm", "session_id": sid}).json()
    assert asked["status"] == "needs_input"
    assert asked["pending_question"]["questions"][0]["question"] == "Where should the reminder reach you?"
    # Saved with the chat: a reload still shows the card.
    stored = client.get(f"/api/agent/sessions/{sid}").json()
    assert stored["metadata"]["pending"]["question"]["questions"][0]["header"] == "Alerts"

    done = client.post(f"/api/agent/sessions/{sid}/answer",
                       json={"answers": {"Where should the reminder reach you?": "Slack"}}).json()
    assert done["status"] == "completed"
    assert "Where should the reminder reach you? → Slack" in done["response"]
    assert "pending" not in client.get(f"/api/agent/sessions/{sid}").json()["metadata"]


def test_answers_can_pick_several_or_be_typed(client, llm):
    many = {**QUESTION, "multi_select": True}
    llm.script = lambda m, t: ({"content": m[-1]["content"], "tool_calls": []} if m[-1]["role"] == "tool"
                               else (ASK_USER, {"questions": [many]}))
    sid = session(client)
    client.post("/api/agent/run", json={"message": "every day at 9 send me a summary", "session_id": sid})
    done = client.post(f"/api/agent/sessions/{sid}/answer",
                       json={"answers": {"Where should the reminder reach you?": ["Nexus pop-up", "My phone"]}}).json()
    assert "Nexus pop-up, My phone" in done["response"]


def test_bad_questions_go_back_to_the_model_not_the_user(client, llm):
    calls = []

    def script(messages, tools):
        calls.append(messages[-1])
        if messages[-1]["role"] == "tool":
            return {"content": "ok", "tool_calls": []}
        return (ASK_USER, {"questions": [{"question": "Which?", "options": []}]})

    llm.script = script
    result = client.post("/api/agent/run", json={"message": "remind me daily", "session_id": session(client)}).json()
    assert result["status"] == "completed"
    assert "1 to 4 options" in calls[-1]["content"]


def test_answering_with_nothing_pending_is_refused(client):
    assert client.post(f"/api/agent/sessions/{session(client)}/answer", json={"answers": {"x": "y"}}).status_code == 409


def test_the_question_tool_is_only_offered_when_the_agent_can_act(client, llm):
    client.post("/api/agent/run", json={"message": "what is the capital of France", "session_id": session(client)})
    assert not any(ASK_USER in c.get("tools", []) for c in llm.calls)
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "remind me to drink water every hour", "session_id": session(client)})
    assert ASK_USER in next(c for c in llm.calls if c["kind"] == "tools")["tools"]


def test_a_reminder_with_no_alert_channel_asks_before_the_approval(client, llm, monkeypatch):
    """Where the reminder goes is the user's call: create_workflow refuses until they've been asked (or said)."""
    from app import knowledge
    from app.workflows import drafting

    async def missing(llm, task, description):
        return True

    monkeypatch.setattr(knowledge, "alert_channel_missing", missing)

    async def draft(description):
        return {"name": "Meds", "description": description, "warnings": [], "edges": [],
                "nodes": [{"id": "t", "type": "trigger", "config": {"trigger_type": "manual"}}]}

    monkeypatch.setattr(drafting, "draft_workflow", draft)
    seen = []

    def script(messages, tools):
        last = messages[-1]
        seen.append(last.get("content") or "")
        if last["role"] == "tool" and "ask the user where" in last["content"]:
            return (ASK_USER, {"questions": [{"question": "Where should the reminder reach you?",
                                              "options": [{"label": "Nexus pop-up"}]}]})
        if last["role"] == "tool" and last["content"].startswith("The user answered"):
            return ("nexus__create_workflow", {"description": "Daily at 2 pm remind me to take my medicines, as a Nexus pop-up"})
        if last["role"] == "tool":
            return {"content": "Done.", "tool_calls": []}
        return ("nexus__create_workflow", {"description": "Every day at 2 pm, remind me to take my medicines"})

    llm.script = script
    sid = session(client)
    first = client.post("/api/agent/run", json={"message": "Create a workflow to remind me to take my medicines daily at 2pm",
                                                "session_id": sid}).json()
    assert first["status"] == "needs_input"  # the question, not the approval
    assert "Nexus pop-up" in seen[-1] or any("Nexus pop-up" in s for s in seen)
    second = client.post(f"/api/agent/sessions/{sid}/answer",
                         json={"answers": {"Where should the reminder reach you?": "Nexus pop-up"}}).json()
    assert second["status"] == "needs_approval" and second["pending_action"]["tool"] == "nexus__create_workflow"
    done = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).json()
    assert done["status"] == "completed"
    for w in client.get("/api/workflows").json():
        if w["name"] == "Meds":
            client.delete(f"/api/workflows/{w['id']}")


def test_saying_where_up_front_skips_the_question(client, llm, monkeypatch):
    from app import knowledge

    async def says_where(llm, task, description):
        return False

    monkeypatch.setattr(knowledge, "alert_channel_missing", says_where)
    llm.script = lambda m, t: ({"content": "ok", "tool_calls": []} if m[-1]["role"] == "tool"
                               else ("nexus__create_workflow", {"description": "Daily at 2 pm send me a pop-up to take meds"}))
    result = client.post("/api/agent/run", json={"message": "Remind me with a pop-up daily at 2pm to take meds",
                                                 "session_id": session(client)}).json()
    assert result["status"] == "needs_approval"


def test_the_model_decides_whether_a_reminder_says_where_to_alert():
    """No keyword lists: a small model call reads the request in any wording or language."""
    import asyncio

    from app.knowledge import alert_channel_missing

    class Answers:
        def __init__(self, reply):
            self.reply, self.prompts = reply, []

        async def chat(self, messages, **kwargs):
            self.prompts.append(messages[-1]["content"])
            return {"content": self.reply}

    def check(reply, task="Recuérdame tomar mis medicinas a las 2"):
        model = Answers(reply)
        result = asyncio.run(alert_channel_missing(model, task, "Daily at 2 pm, remind the user to take medicines"))
        return result, model.prompts

    missing, prompts = check('{"alerts_user": true, "says_where": false}')
    assert missing is True and "Recuérdame tomar mis medicinas" in prompts[0]
    assert check('Sure: {"alerts_user": true, "says_where": true}')[0] is False
    assert check('{"alerts_user": false, "says_where": false}')[0] is False  # not a reminder at all
    assert check("I am not sure")[0] is True  # unreadable: play safe and ask

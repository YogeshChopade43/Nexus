"""Section 4: streaming, approval before risky tools, tool policies, chat → workflow, attachments."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mcp.manager import default_policy

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class ToolLLM:
    """Calls ``tool`` once when the message mentions ``trigger_word``, then answers."""
    provider_name = "fake"
    default_model = "fake"

    def __init__(self, tool="agent_echo__echo", args=None, trigger_word="please"):
        self.tool, self.args, self.trigger_word = tool, args or {"text": "hi"}, trigger_word
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return {"content": f"plain: {messages[-1]['content'][:40]}"}

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(messages)
        for chunk in ("Hel", "lo", "!"):
            yield chunk

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(messages)
        last = messages[-1]
        if last["role"] == "tool":
            return {"content": f"Done: {last['content'][:60]}", "tool_calls": []}
        if self.trigger_word in str(last.get("content", "")):
            return {"content": "", "tool_calls": [{"id": "c1", "name": self.tool, "arguments": json.dumps(self.args)}]}
        return {"content": "", "tool_calls": []}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={"name": "Agent Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE]})
        assert r.json()["status"] == "connected", r.json()
        c.server_id = r.json()["id"]
        yield c


@pytest.fixture
def llm(monkeypatch):
    fake = ToolLLM()
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (fake, {}))
    return fake


def session(client):
    return client.post("/api/agent/sessions", json={}).json()["session_id"]


def set_policies(client, policies):
    r = client.patch(f"/api/mcp/servers/{client.server_id}", json={"tool_policies": policies})
    assert r.status_code == 200, r.text
    return r.json()


def test_default_policy_by_risk():
    assert default_policy("send_message", None) == "ask"
    assert default_policy("delete_page", None) == "ask"
    assert default_policy("list_items", None) == "allow"
    assert default_policy("create_issue", {"read_only_hint": True}) == "allow"
    assert default_policy("lookup", {"destructive_hint": True}) == "ask"


def test_tool_policies_are_listed_and_block_hides_tools(client):
    server = set_policies(client, {"list_items": "block"})
    policies = {t["remote_name"]: t["policy"] for t in server["tools"]}
    assert policies["echo"] == "allow" and "list_items" not in policies
    assert "agent_echo__list_items" not in client.get("/api/tools/available").json()["tools"]
    blocked = {b["remote_name"]: b["policy"] for b in server["blocked_tools"]}
    assert blocked == {"list_items": "block"}
    set_policies(client, {})
    assert "agent_echo__list_items" in client.get("/api/tools/available").json()["tools"]


def test_approval_flow(client, llm):
    set_policies(client, {"echo": "ask"})
    sid = session(client)
    paused = client.post("/api/agent/run", json={"message": "echo please", "session_id": sid}).json()
    assert paused["status"] == "needs_approval"
    assert paused["pending_action"]["tool"] == "agent_echo__echo" and paused["pending_action"]["arguments"] == {"text": "hi"}

    done = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).json()
    assert done["status"] == "completed" and "echo: hi" in done["response"]
    assert any(e["type"] == "tool_executed" for e in done["events"])
    assert client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).status_code == 409

    client.post("/api/agent/run", json={"message": "again please", "session_id": sid})
    denied = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": False}).json()
    assert denied["status"] == "completed" and "declined" in denied["response"].lower()
    assert not any(e["type"] == "tool_executed" for e in denied["events"])
    set_policies(client, {})


def _sse(client, body):
    events = []
    with client.stream("POST", "/api/agent/run/stream", json=body) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_streaming_shows_tool_activity(client, llm):
    events = _sse(client, {"message": "echo please", "session_id": session(client)})
    kinds = [e["type"] for e in events]
    assert kinds.index("tool_call") < kinds.index("tool_result") < kinds.index("done")
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["tool"] == "agent_echo__echo" and call["arguments"] == {"text": "hi"}
    assert "echo: hi" in events[-1]["response"]


def test_streaming_plain_answer_is_token_by_token(client, llm):
    events = _sse(client, {"message": "just talk", "session_id": session(client)})
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Hel", "lo", "!"]
    assert events[-1]["type"] == "done" and events[-1]["response"] == "Hello!"


def test_streaming_pauses_for_approval(client, llm):
    set_policies(client, {"echo": "ask"})
    events = _sse(client, {"message": "echo please", "session_id": session(client)})
    assert events[-1]["type"] == "done" and events[-1]["status"] == "needs_approval"
    assert any(e["type"] == "approval_needed" for e in events)
    set_policies(client, {})


def test_conversation_to_workflow(client, llm):
    llm.tool, llm.args = "agent_echo__list_items", {"count": 3}
    sid = session(client)
    client.post("/api/agent/run", json={"message": "list please", "session_id": sid})
    wf = client.post(f"/api/agent/sessions/{sid}/workflow").json()
    types = [n["type"] for n in wf["nodes"]]
    assert types[0] == "trigger" and "action" in types and types[-1] == "llm"
    action = next(n for n in wf["nodes"] if n["type"] == "action")
    assert action["config"] == {"tool": "agent_echo__list_items", "parameters": {"count": 3}}
    empty = session(client)
    client.post("/api/agent/run", json={"message": "just talk", "session_id": empty})
    assert client.post(f"/api/agent/sessions/{empty}/workflow").status_code == 400


def test_attachments_reach_the_model(client, llm):
    r = client.post("/api/agent/run", json={"message": "summarize the file", "session_id": session(client),
                                             "attachments": [{"name": "notes.txt", "content": "mango season starts in April"}]})
    assert r.status_code == 200
    user_message = llm.calls[-1][-1]["content"]
    assert "notes.txt" in user_message and "mango season starts in April" in user_message
    too_many = [{"name": f"f{i}.txt", "content": "x"} for i in range(6)]
    assert client.post("/api/agent/run", json={"message": "x", "attachments": too_many}).status_code == 422

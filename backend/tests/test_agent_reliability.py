"""The agent under failure: AI-service errors, bad tool arguments, follow-ups, final answers and repeated calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm.errors import ProviderError
from app.main import app

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={"name": "Reliable Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE]})
        assert r.json()["status"] == "connected", r.json()
        c.server_id = r.json()["id"]
        yield c


def session(client):
    return client.post("/api/agent/sessions", json={}).json()["session_id"]


def set_policies(client, policies):
    r = client.patch(f"/api/mcp/servers/{client.server_id}", json={"tool_policies": policies})
    assert r.status_code == 200, r.text


def use_llm(monkeypatch, fake):
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (fake, {}))
    return fake


def call(name, arguments, call_id="c1"):
    return {"id": call_id, "name": name, "arguments": json.dumps(arguments)}


class FakeLLM:
    provider_name = "fake"
    default_model = "fake"

    def __init__(self):
        self.calls, self.plain_called = [], False

    async def chat(self, messages, **kwargs):
        self.plain_called = True
        return {"content": "plain answer"}

    async def chat_stream(self, messages, **kwargs):
        self.plain_called = True
        yield "plain answer"


class BrokenLLM(FakeLLM):
    """Calls echo once, then the AI service stays overloaded (as if Metered's retries ran out)."""

    def __init__(self, fail_first=False):
        super().__init__()
        self.fail_first = fail_first

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(messages)
        if self.fail_first or messages[-1]["role"] == "tool":
            raise ProviderError("anthropic", 529)
        return {"content": "", "tool_calls": [call("reliable_echo__echo", {"text": "hi"})]}


def test_provider_failure_mid_task_is_reported_not_papered_over(client, monkeypatch):
    fake = use_llm(monkeypatch, BrokenLLM())
    r = client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)}).json()
    assert r["status"] == "error"
    assert r["response"] == ("Anthropic is overloaded right now (HTTP 529). Try again in a minute. "
                             "Nothing was changed after the last completed step.")
    assert not fake.plain_called


def test_provider_failure_before_any_tool_has_no_nothing_changed_note(client, monkeypatch):
    fake = use_llm(monkeypatch, BrokenLLM(fail_first=True))
    r = client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)}).json()
    assert r["status"] == "error" and r["response"] == "Anthropic is overloaded right now (HTTP 529). Try again in a minute."
    assert not fake.plain_called


def test_provider_failure_after_approval_is_reported(client, monkeypatch):
    set_policies(client, {"echo": "ask"})
    use_llm(monkeypatch, BrokenLLM())
    sid = session(client)
    paused = client.post("/api/agent/run", json={"message": "echo please", "session_id": sid}).json()
    assert paused["status"] == "needs_approval"
    r = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True})
    set_policies(client, {})
    assert r.status_code == 200 and r.json()["status"] == "error" and "HTTP 529" in r.json()["response"]


class OneCallLLM(FakeLLM):
    """Makes one tool call, then records what the tool returned and answers "done"."""

    def __init__(self, tool, arguments):
        super().__init__()
        self.tool, self.arguments, self.tool_messages = tool, arguments, []

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(messages)
        if messages[-1]["role"] == "tool" or self.arguments is None:
            if messages[-1]["role"] == "tool":
                self.tool_messages.append(messages[-1]["content"])
            return {"content": "done", "tool_calls": []}
        return {"content": "", "tool_calls": [call(self.tool, self.arguments)]}


def test_wrong_argument_type_is_sent_back_not_run(client, monkeypatch):
    fake = use_llm(monkeypatch, OneCallLLM("reliable_echo__list_items", {"count": "three"}))
    r = client.post("/api/agent/run", json={"message": "list please", "session_id": session(client)}).json()
    tool_msg = fake.tool_messages[0]
    assert tool_msg.startswith("Not run: the arguments for reliable_echo__list_items don't match its schema:")
    assert "count" in tool_msg and "integer" in tool_msg
    assert [e["type"] for e in r["events"] if e.get("tool_name") == "reliable_echo__list_items"] == ["tool_error"]


def test_schema_problems_lists_at_most_three():
    from app.agent.abstract import schema_problems

    schema = {"type": "object", "properties": {k: {"type": "integer"} for k in "abcd"}}
    problems = schema_problems(schema, {k: "x" for k in "abcd"})
    assert len(problems) == 3 and problems[0].startswith("a: 'x' is not of type 'integer'")


def test_broken_schema_skips_validation():
    from app.agent.abstract import schema_problems

    assert schema_problems({"type": "not-a-type"}, {"a": 1}) == []


def test_history_carries_the_previous_replys_tool_results():
    from app.agent.abstract import clean_history

    saved = [{"role": "user", "content": "list"},
             {"role": "assistant", "content": "Here they are", "events": [
                 {"type": "tool_executed", "tool_name": "gh__list_prs", "arguments": {"repo": "x"},
                  "summary": "2 PRs", "data": {"items": [{"id": 4242}]}}]}]
    history = clean_history(saved, with_tools=True)
    assert "(Context for you, not shown to the user: tools used for this reply)" in history[1]["content"]
    assert 'gh__list_prs({"repo": "x"}) -> 2 PRs; data: ' in history[1]["content"] and "4242" in history[1]["content"]
    assert clean_history(saved)[1]["content"] == "Here they are"


def test_history_note_is_capped():
    from app.agent.abstract import clean_history

    big = {"type": "tool_executed", "tool_name": "t", "arguments": {}, "summary": "s", "data": {"x": "y" * 5000}}
    content = clean_history([{"role": "assistant", "content": "a", "events": [big] * 5}], with_tools=True)[0]["content"]
    assert len(content) <= len("a") + 4000 + 100


def test_messages_without_successful_tools_are_unchanged():
    from app.agent.abstract import clean_history

    saved = [{"role": "assistant", "content": "a", "events": [{"type": "tool_error", "tool_name": "t", "error": "x"}]},
             {"role": "assistant", "content": "b"}]
    assert [m["content"] for m in clean_history(saved, with_tools=True)] == ["a", "b"]


def test_follow_up_turn_sees_the_earlier_result(client, monkeypatch):
    fake = use_llm(monkeypatch, OneCallLLM("reliable_echo__list_items", {"count": 2}))
    sid = session(client)
    client.post("/api/agent/run", json={"message": "list please", "session_id": sid})
    fake.arguments = None  # the follow-up makes no tool call
    client.post("/api/agent/run", json={"message": "thanks", "session_id": sid})
    sent = json.dumps(fake.calls[-1])
    assert "reliable_echo__list_items" in sent and "tools used for this reply" in sent


class StubbornLLM(FakeLLM):
    """Calls a tool every round; asked for the final answer, it answers (and still tries a tool, which is ignored)."""

    def __init__(self, args_fn, tool="reliable_echo__echo", fail_final=None):
        super().__init__()
        self.args_fn, self.tool, self.fail_final, self.rounds = args_fn, tool, fail_final, 0

    async def chat_with_tools(self, messages, tools, **kwargs):
        from app.agent.abstract import FINAL_ASK

        self.calls.append(messages)
        if messages[-1]["role"] == "user" and messages[-1]["content"] == FINAL_ASK:
            if self.fail_final:
                raise self.fail_final
            return {"content": "final answer", "tool_calls": [call(self.tool, self.args_fn(99), "late")]}
        self.rounds += 1
        return {"content": "", "tool_calls": [call(self.tool, self.args_fn(self.rounds), f"c{self.rounds}")]}


def test_identical_calls_run_twice_then_stop(client, monkeypatch):
    use_llm(monkeypatch, StubbornLLM(lambda n: {"text": "hi"}))
    r = client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)}).json()
    types = [e["type"] for e in r["events"]]
    assert types.count("tool_executed") == 2 and "tool_repeat" in types and "repeat_limit" in types
    assert r["response"].startswith("final answer") and "repeating the same step" in r["response"]


def test_step_limit_is_15_and_ends_with_a_real_answer(client, monkeypatch):
    use_llm(monkeypatch, StubbornLLM(lambda n: {"text": f"hi {n}"}))  # always different: no repeat stop
    r = client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)}).json()
    assert sum(e["type"] == "tool_executed" for e in r["events"]) == 15
    assert r["response"].startswith("final answer") and "15 rounds" in r["response"]


def test_final_answer_provider_failure_is_reported(client, monkeypatch):
    fake = StubbornLLM(lambda n: {"text": f"hi {n}"}, fail_final=ProviderError("anthropic", 503))
    use_llm(monkeypatch, fake)
    r = client.post("/api/agent/run", json={"message": "echo please", "session_id": session(client)}).json()
    assert r["status"] == "error" and "HTTP 503" in r["response"] and not fake.plain_called


def test_helper_tools_are_exempt_from_repeat_detection(client, monkeypatch):
    use_llm(monkeypatch, StubbornLLM(lambda n: {"query": "echo"}, tool="nexus_find_tools"))
    r = client.post("/api/agent/run", json={"message": "find please", "session_id": session(client)}).json()
    assert "repeat_limit" not in [e["type"] for e in r["events"]]


def test_unresolvable_ref_skips_validation():
    from app.agent.abstract import schema_problems

    assert schema_problems({"type": "object", "properties": {"a": {"$ref": "#/$defs/Missing"}}}, {"a": 1}) == []


def test_values_apps_used_to_accept_still_pass():
    from app.agent.abstract import schema_problems

    schema = {"type": "object", "properties": {"count": {"type": "integer"}, "ratio": {"type": "number"},
                                               "on": {"type": "boolean"}, "name": {"type": "string"}},
              "required": ["count"]}
    assert schema_problems(schema, {"count": "5", "ratio": "0.5", "on": "true", "name": None}) == []
    assert schema_problems(schema, {"count": "three"}) != []


def test_declined_calls_dont_count_as_repeats(client, monkeypatch):
    set_policies(client, {"echo": "ask"})
    use_llm(monkeypatch, StubbornLLM(lambda n: {"text": "hi"}))
    sid = session(client)
    assert client.post("/api/agent/run", json={"message": "echo please", "session_id": sid}).json()["status"] == "needs_approval"
    for _ in range(2):
        assert client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": False}).json()["status"] == "needs_approval"
    r = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).json()
    set_policies(client, {})
    assert "tool_executed" in [e["type"] for e in r["events"]]


def test_a_repeat_never_asks_for_approval(client, monkeypatch):
    set_policies(client, {"echo": "ask"})
    use_llm(monkeypatch, StubbornLLM(lambda n: {"text": "hi"}))
    sid = session(client)
    client.post("/api/agent/run", json={"message": "echo please", "session_id": sid})
    client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True})
    r = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).json()
    set_policies(client, {})
    assert r["status"] == "completed" and "repeat_limit" in [e["type"] for e in r["events"]]


def test_chat_without_tools_shows_the_plain_error():
    import asyncio

    from app.agent.abstract import BaseAgent
    from app.tools.registry import ToolRegistry

    class Down(FakeLLM):
        async def chat(self, messages, **kwargs):
            raise ProviderError("anthropic", 529)

    result = asyncio.run(BaseAgent(ToolRegistry(), {}).run(task="hello", llm_provider=Down(), history=[]))
    assert result["status"] == "error"
    assert result["response"] == "Anthropic is overloaded right now (HTTP 529). Try again in a minute."

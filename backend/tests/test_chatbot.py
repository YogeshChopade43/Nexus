"""Chat improvements: tool selection, long results, step limit, history summary, retry, search,
per-chat settings, cost per reply, approval streaming, documents (RAG) and memory."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.abstract import FIND_TOOLS, MAX_TOOL_ITERATIONS, MAX_TOOLS_PER_TURN, READ_RESULT, BaseAgent
from app.agent.sessions import append_message, get_session
from app.core.database import get_connection
from app.llm.metering import Metered
from app.main import app
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class ScriptedLLM:
    """Answers with ``script(messages, tools)``: a dict reply, or a (tool, args) tuple to call a tool."""
    provider_name = "fake"
    default_model = "fake-model"

    def __init__(self, script=None):
        self.script = script or (lambda messages, tools: {"content": "ok", "tool_calls": []})
        self.calls: list[dict] = []

    def _reply(self, out):
        if isinstance(out, tuple):
            return {"content": "", "tool_calls": [{"id": f"c{len(self.calls)}", "name": out[0], "arguments": json.dumps(out[1])}],
                    "usage": {"input_tokens": 10, "output_tokens": 2}, "model": "fake-model"}
        return {"usage": {"input_tokens": 10, "output_tokens": 2}, "model": "fake-model", **out}

    async def chat(self, messages, **kwargs):
        self.calls.append({"kind": "chat", "messages": messages, "kwargs": kwargs})
        return {"content": "summary: talked about mangoes", "usage": {"input_tokens": 5, "output_tokens": 5}, "model": "fake-model"}

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append({"kind": "tools", "messages": messages, "tools": [t["name"] for t in tools], "kwargs": kwargs})
        return self._reply(self.script(messages, [t["name"] for t in tools]))

    async def chat_stream(self, messages, **kwargs):
        self.calls.append({"kind": "stream", "messages": messages, "kwargs": kwargs})
        for chunk in ("Str", "eam", "ed"):
            yield chunk


class Dummy(Tool):
    def __init__(self, name, description, output="done"):
        super().__init__(f"app__{name}", "app", description)
        self.output = output

    async def execute(self, parameters):
        return {"text": self.output}


def run(agent, task, llm, history=None):
    return asyncio.run(agent.run(task=task, llm_provider=llm, history=history or []))


# ---- agent loop (no server needed) -------------------------------------------------------

def test_many_tools_are_narrowed_and_find_tools_recovers():
    registry = ToolRegistry()
    for i in range(40):
        registry.register(Dummy(f"tool_{i}", f"Unrelated operation number {i}"))
    registry.register(Dummy("tool_send_invoice", "Send an invoice to a customer", output="invoice sent"))

    def script(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and "invoice sent" in last["content"]:
            return {"content": f"Done: {last['content'][:40]}", "tool_calls": []}
        if "app__tool_send_invoice" in tools:
            return ("app__tool_send_invoice", {})
        return (FIND_TOOLS, {"query": "invoice"})

    llm = ScriptedLLM(script)
    result = run(BaseAgent(registry, {"app": True}), "please bill ACME", llm)
    first = llm.calls[0]["tools"]
    assert first == [FIND_TOOLS]  # nothing matches "bill ACME": no unrelated tools are sent, only the finder
    assert "app__tool_send_invoice" in llm.calls[1]["tools"]  # found, now offered
    assert result["status"] == "completed" and "invoice sent" in result["response"]

    # A request that names the tool's words gets it offered straight away.
    llm = ScriptedLLM(lambda m, t: {"content": "ok", "tool_calls": []})
    run(BaseAgent(registry, {"app": True}), "send the invoice", llm)
    assert "app__tool_send_invoice" in llm.calls[0]["tools"]


def test_small_talk_sends_only_builtin_tools():
    """A greeting matches no tool, so app tools (often hundreds of tokens each) are not sent."""
    registry = ToolRegistry()
    registry.register(Dummy("tool_send_invoice", "Send an invoice to a customer"))
    registry.register(Dummy("tool_list_pages", "List pages in the workspace"))
    builtin = Dummy("remember", "Save a fact about the user")
    builtin.app_id = "nexus"
    registry.register(builtin)
    llm = ScriptedLLM()
    run(BaseAgent(registry, {"app": True, "nexus": True}), "hi", llm)
    assert sorted(llm.calls[0]["tools"]) == sorted(["app__remember", FIND_TOOLS])


def test_unused_schema_definitions_are_dropped():
    from app.mcp.manager import prune_unused_defs

    schema = {"$defs": {"used": {"type": "object", "properties": {"x": {"$ref": "#/$defs/nested"}}},
                        "nested": {"type": "string"}, "unused": {"type": "string"}},
              "type": "object", "properties": {"a": {"$ref": "#/$defs/used"}}}
    assert set(prune_unused_defs(schema)["$defs"]) == {"used", "nested"}
    assert prune_unused_defs({"$defs": {"u": {}}, "type": "object", "properties": {}}) == {"type": "object", "properties": {}}


def test_large_results_can_be_paged():
    registry = ToolRegistry()
    big = "".join(f"line {i:05d}\n" for i in range(3000))  # ~33k characters
    registry.register(Dummy("export", "Export everything", output=big))
    seen = {}

    def script(messages, tools):
        last = messages[-1]
        if last["role"] == "user":
            return ("app__export", {})
        if READ_RESULT not in seen:
            seen[READ_RESULT] = last["content"]
            assert READ_RESULT in tools
            return (READ_RESULT, {"result_id": "c1", "offset": 8000})
        seen["page"] = last["content"]
        return {"content": "read it", "tool_calls": []}

    run(BaseAgent(registry, {"app": True}), "export", ScriptedLLM(script))
    assert "Call nexus_read_result" in seen[READ_RESULT]
    assert seen["page"].startswith("[characters 8000-16000 of") and "line" in seen["page"]


def test_step_limit_is_explained():
    registry = ToolRegistry()
    registry.register(Dummy("poke", "Poke"))
    # A different argument each round, so it's the step limit that stops it, not repeat detection.
    result = run(BaseAgent(registry, {"app": True}), "loop", ScriptedLLM(lambda m, t: ("app__poke", {"n": len(m)})))
    assert any(e["type"] == "step_limit" for e in result["events"])
    assert f"stopped after {MAX_TOOL_ITERATIONS} rounds" in result["response"]


# ---- chat API ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/mcp/servers", json={"name": "Chat Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE]})
        assert r.json()["status"] == "connected", r.json()
        c.server = r.json()
        yield c
        c.delete(f"/api/mcp/servers/{c.server['id']}")


@pytest.fixture
def llm(monkeypatch):
    fake = ScriptedLLM()
    import app.api.routes.agent as agent_route
    monkeypatch.setattr(agent_route, "get_default_llm_provider", lambda: (Metered(fake, None, {"model": "fake-model"}), {}))
    return fake


def new_session(client):
    return client.post("/api/agent/sessions", json={}).json()["session_id"]


def test_long_chats_are_summarized(client, llm):
    sid = new_session(client)
    for i in range(30):
        append_message(sid, {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i} about mangoes"})
    client.post("/api/agent/run", json={"message": "what did we discuss?", "session_id": sid})
    summarize = next(c for c in llm.calls if c["kind"] == "chat")
    assert "Summarize" in summarize["messages"][0]["content"] and "message 0 about mangoes" in summarize["messages"][1]["content"]
    answer = next(c for c in llm.calls if c["kind"] == "tools")
    assert "summary: talked about mangoes" in answer["messages"][0]["content"]
    assert len([m for m in answer["messages"] if m["role"] in ("user", "assistant")]) == 21  # 20 recent + this one
    metadata = get_session(sid)["metadata"]
    assert metadata["summary_upto"] == 10
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "and now?", "session_id": sid})
    assert not any(c["kind"] == "chat" for c in llm.calls)  # only 2 more messages: summary reused


def test_retry_rewinds_the_last_turn(client, llm):
    sid = new_session(client)
    client.post("/api/agent/run", json={"message": "first question", "session_id": sid})
    client.post("/api/agent/run", json={"message": "second question", "session_id": sid})
    r = client.post(f"/api/agent/sessions/{sid}/rewind")
    assert r.json() == {"message": "second question"}
    assert [m["content"] for m in get_session(sid)["messages"]] == ["first question", "ok"]
    assert client.post(f"/api/agent/sessions/{new_session(client)}/rewind").status_code == 409


def test_attached_files_are_kept_with_the_message(client, llm):
    sid = new_session(client)
    ref = {"id": "0123456789abcdef", "name": "notes.txt", "size": 5, "url": "/api/files/0123456789abcdef/notes.txt"}
    client.post("/api/agent/run", json={"message": "read this", "session_id": sid, "files": [ref]})
    assert get_session(sid)["messages"][0]["files"] == [ref]


def test_conversation_search(client, llm):
    sid = new_session(client)
    client.post("/api/agent/run", json={"message": "Notes about the café menu 100%", "session_id": sid})
    found = lambda q: [s["session_id"] for s in client.get("/api/agent/sessions", params={"q": q}).json()]  # noqa: E731
    assert sid in found("café")  # non-ASCII text is stored escaped in JSON; still found
    assert sid in found("100%") and sid not in found("10_%")
    assert sid not in found("zebra")


def test_chat_settings_servers_instructions_temperature_and_cost(client, llm):
    client.patch("/api/settings/user", json={"llmPrices": {"fake-model": {"input": 1000, "output": 2000}}})
    sid = new_session(client)
    settings = {"servers": [], "instructions": "Always answer in French.", "temperature": 0.3}
    r = client.post("/api/agent/run", json={"message": "hello", "session_id": sid, "chat_settings": settings}).json()
    # No servers chosen (and nothing else applies): no tools at all, so a plain reply.
    assert not any(c["kind"] == "tools" for c in llm.calls)
    call = next(c for c in llm.calls if c["kind"] == "chat")
    assert "Always answer in French." in call["messages"][0]["content"]
    assert call["kwargs"].get("temperature") == 0.3
    assert r["usage"]["input_tokens"] == 5 and r["usage"]["output_tokens"] == 5 and r["usage"]["cost"] == 0.015
    assert get_session(sid)["messages"][-1]["usage"]["cost"] == 0.015
    # Saved with the conversation: the next message uses them without resending.
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "again", "session_id": sid})
    assert next(c for c in llm.calls if c["kind"] == "chat")["kwargs"].get("temperature") == 0.3
    assert client.put(f"/api/agent/sessions/{sid}/settings", json={"servers": None, "instructions": "", "temperature": None}).status_code == 200
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "echo this back", "session_id": sid})
    assert any(t.startswith("chat_echo__") for t in next(c for c in llm.calls if c["kind"] == "tools")["tools"])
    client.patch("/api/settings/user", json={"llmPrices": {}})


def test_approval_answer_streams(client, llm):
    client.patch(f"/api/mcp/servers/{client.server['id']}", json={"tool_policies": {"echo": "ask"}})
    try:
        llm.script = lambda m, t: ({"content": "", "tool_calls": []} if m[-1]["role"] == "tool" else ("chat_echo__echo", {"text": "hi"}))
        sid = new_session(client)
        first = client.post("/api/agent/run", json={"message": "echo it", "session_id": sid}).json()
        assert first["status"] == "needs_approval"
        with client.stream("POST", f"/api/agent/sessions/{sid}/approval/stream", json={"approved": True}) as r:
            events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert "tool_call" in types and "delta" in types and types[-1] == "done"
        assert events[-1]["status"] == "completed"
    finally:
        client.patch(f"/api/mcp/servers/{client.server['id']}", json={"tool_policies": {}})


# ---- documents and memory ------------------------------------------------------------------

def test_memory_is_remembered_across_chats(client, llm):
    llm.script = lambda m, t: (
        {"content": "Noted.", "tool_calls": []} if m[-1]["role"] == "tool"
        else ("nexus__remember", {"fact": "My main Notion database is Roadmap"}))
    client.post("/api/agent/run", json={"message": "remember my db", "session_id": new_session(client)})
    memories = client.get("/api/knowledge/memories").json()
    assert any(m["content"] == "My main Notion database is Roadmap" for m in memories)
    llm.calls.clear()
    llm.script = lambda m, t: {"content": "ok", "tool_calls": []}
    client.post("/api/agent/run", json={"message": "which db?", "session_id": new_session(client)})
    system = next(c for c in llm.calls if c["kind"] == "tools")["messages"][0]["content"]
    assert "My main Notion database is Roadmap" in system
    for m in memories:
        assert client.delete(f"/api/knowledge/memories/{m['id']}").status_code == 204


def test_stop_keeps_what_was_said_so_far(client):
    """Closing the stream (the Stop button) cancels the run and saves the partial answer."""
    from app.api.routes.agent import _stream

    sid = new_session(client)

    async def work(on_event):
        await on_event({"type": "delta", "text": "Half an answ"})
        await asyncio.sleep(30)

    async def scenario():
        body = _stream(sid, "a question", None, work).body_iterator
        assert "Half an answ" in await body.__anext__()
        await body.aclose()

    asyncio.run(scenario())
    messages = get_session(sid)["messages"]
    assert messages[-2]["content"] == "a question"
    assert messages[-1]["status"] == "cancelled" and "Half an answ" in messages[-1]["content"]


def test_plain_chat_streams_when_no_tools_apply(client, llm, monkeypatch):
    """No servers chosen, no documents, nothing to remember: the reply streams word by word."""
    import app.api.routes.agent as agent_route

    monkeypatch.setattr(agent_route, "readable_document_names", lambda *a, **k: [])
    sid = new_session(client)
    client.put(f"/api/agent/sessions/{sid}/settings", json={"servers": [], "instructions": "", "temperature": None})
    with client.stream("POST", "/api/agent/run/stream", json={"message": "tell me a joke", "session_id": sid}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Str", "eam", "ed"]
    assert not any(c["kind"] == "tools" for c in llm.calls)


def test_personal_questions_get_the_who_am_i_tool():
    """'my repos' needs the account's own name: guessing it from other context (a resume) gets it wrong."""
    from app.agent.tool_selection import rank_tools

    tools = [("github__search_repositories", "Find GitHub repositories by name, description or topics"),
             ("github__list_branches", "List branches in a GitHub repository"),
             ("github__get_me", "Get details of the authenticated GitHub user")]
    assert "github__get_me" in rank_tools("What are my github repo names?", tools, 2, min_score=1)
    # No keyword detection: any phrasing or language gets it (one small tool per app).
    assert "github__get_me" in rank_tools("¿cuáles son mis repositorios de github?", tools, 2, min_score=1)
    assert "github__get_me" in rank_tools("list branches", tools, 2, min_score=1)


def test_naming_an_app_prefers_that_apps_tools():
    from app.agent.tool_selection import rank_tools

    tools = [("notion__notion-search", "Search the user's Notion workspace and connected sources such as Slack, GitHub"),
             ("notion__notion-get-users", "List users; use 'self' to get the current user"),
             ("github__search_repositories", "Find GitHub repositories by name, description or topics"),
             ("github__get_me", "Get details of the authenticated GitHub user")]
    assert rank_tools("search github for mcp servers", tools, 1, min_score=1)[0] == "github__search_repositories"
    mine = rank_tools("What are my github repo names?", tools, 2, min_score=1)
    assert "github__get_me" in mine and "notion__notion-get-users" not in mine


def test_tool_errors_reach_the_model_verbatim_with_a_no_guessing_rule():
    """A failed GitHub search was explained to the user as a 'permission issue' when the real error said the user
    didn't exist: the model gets the exact error and is told to report it, not speculate."""

    class Failing(Dummy):
        async def execute(self, parameters):
            raise RuntimeError("Validation Failed: the listed users cannot be searched")

    registry = ToolRegistry()
    registry.register(Failing("search_repos", "Search repositories"))

    def script(messages, tools):
        if messages[-1]["role"] == "tool":
            return {"content": "done", "tool_calls": []}
        return ("app__search_repos", {})

    llm = ScriptedLLM(script)
    result = run(BaseAgent(registry, {"app": True}), "search repos please", llm)
    tool_reply = llm.calls[-1]["messages"][-1]["content"]
    assert "Validation Failed: the listed users cannot be searched" in tool_reply
    assert "do not guess" in tool_reply.lower()
    assert any(e["type"] == "tool_error" for e in result["events"])


def test_reminder_in_chat_becomes_a_workflow_after_approval(client, llm, monkeypatch):
    """'Remind me ... every day at 11:57 pm' -> the agent proposes a workflow, you approve, it's created and switched on."""
    from app import knowledge
    from app.workflows import drafting

    async def says_where(llm, task, description):
        return False

    monkeypatch.setattr(knowledge, "alert_channel_missing", says_where)

    async def draft(description):
        return {"name": "Medicine reminder", "description": description, "warnings": [], "edges": [{"source": "t", "target": "n"}],
                "nodes": [{"id": "t", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day",
                                                                     "at": "23:57", "timezone": "Asia/Kolkata"}},
                          {"id": "n", "type": "action", "config": {"tool": "nexus__notify",
                                                                   "parameters": {"title": "Take your medicines"}}}]}

    monkeypatch.setattr(drafting, "draft_workflow", draft)
    llm.script = lambda m, t: (
        {"content": "Done: your reminder is set.", "tool_calls": []} if m[-1]["role"] == "tool"
        else ("nexus__create_workflow", {"description": "Every day at 11:57 pm, remind me to take my medicines"}))
    sid = new_session(client)
    asked = client.post("/api/agent/run", json={"message": "Remind me with a pop-up to take my medicines every day at 11:57 pm",
                                                "session_id": sid}).json()
    assert asked["status"] == "needs_approval" and asked["pending_action"]["tool"] == "nexus__create_workflow"
    done = client.post(f"/api/agent/sessions/{sid}/approval", json={"approved": True}).json()
    assert done["status"] == "completed"
    created = next(w for w in client.get("/api/workflows").json() if w["name"] == "Medicine reminder")
    assert created["isActive"] is True
    assert created["trigger_config"]["next_run_at"]
    client.delete(f"/api/workflows/{created['id']}")


def test_create_workflow_is_only_offered_for_automation_requests(client, llm):
    client.post("/api/agent/run", json={"message": "what is the capital of France", "session_id": new_session(client)})
    offered = [t for c in llm.calls if c["kind"] == "tools" for t in c["tools"]]
    assert "nexus__create_workflow" not in offered
    llm.calls.clear()
    client.post("/api/agent/run", json={"message": "every weekday at 9 send me a summary", "session_id": new_session(client)})
    assert "nexus__create_workflow" in next(c for c in llm.calls if c["kind"] == "tools")["tools"]


def test_mentioning_an_app_points_the_agent_at_it(client, llm, monkeypatch):
    """'@Other Echo ...' offers only that app's tools (plus Nexus's own), and the instructions name what was meant."""
    import app.api.routes.agent as agent_route

    other = client.post("/api/mcp/servers", json={"name": "Other Echo", "transport": "stdio", "command": sys.executable,
                                                   "args": [FIXTURE]}).json()
    monkeypatch.setattr(agent_route, "readable_document_names", lambda *a, **k: ["resume.pdf"])
    try:
        client.post("/api/agent/run", json={"message": "@Other Echo echo hello and check @resume.pdf",
                                            "session_id": new_session(client)})
        call = next(c for c in llm.calls if c["kind"] == "tools")
        assert any(t.startswith("other_echo__") for t in call["tools"])
        assert not any(t.startswith("chat_echo__") for t in call["tools"])
        assert "Other Echo" in call["messages"][0]["content"] and "resume.pdf" in call["messages"][0]["content"]
    finally:
        client.delete(f"/api/mcp/servers/{other['id']}")


def test_my_things_get_the_who_am_i_tool_even_without_naming_the_app():
    """'what are my repo names ?' never says GitHub and shares no word with get_me, yet needs it: without it the
    agent searched users for the literal word 'my' and answered with a stranger's repository."""
    from app.agent.tool_selection import rank_tools

    tools = [("github__search_repositories", "Find GitHub repositories by name, description or topics"),
             ("github__pull_request_review_write", "Create a review. Reviews are submitted as the authenticated user"),
             ("github__search_users", "Find GitHub users by username"),
             ("github__get_me", "Get details of the authenticated GitHub user")]
    picked = rank_tools("what are my repo names ?", tools, 2, min_score=1)
    assert "github__get_me" in picked
    assert "github__pull_request_review_write" not in picked  # mentions the user in passing; not a who-am-I tool


def test_step_summaries_read_like_sentences_not_json():
    import json as _json

    summary = BaseAgent._summarize_tool_result
    found = {"total_count": 12, "incomplete_results": False,
             "items": [{"full_name": "YogeshChopade43/Nexus", "id": 1}, {"full_name": "YogeshChopade43/notes", "id": 2}]}
    assert summary("github__search_repositories", {"text": _json.dumps(found)}) == \
        "2 of 12 results: YogeshChopade43/Nexus, YogeshChopade43/notes"
    me = {"login": "YogeshChopade43", "name": "Yogesh Chopade", "avatar_url": "https://x", "public_repos": 4}
    assert summary("github__get_me", {"text": _json.dumps(me)}) == "Login: YogeshChopade43 · Name: Yogesh Chopade"
    assert summary("x__list", {"text": _json.dumps([{"title": "A"}, {"title": "B"}, {"title": "C"}, {"title": "D"}])}) == \
        "4 results: A, B, C…"
    assert summary("x__say", {"text": "Sent the message."}) == "Sent the message."
    assert summary("x__empty", {"text": _json.dumps({"items": []})}) == "No results"


def test_missing_required_values_go_back_to_the_model_with_a_way_forward():
    """GitHub search was called without its required 'query'; the agent then told the user to rephrase. Nexus now
    catches the gap before calling the app and points the model at filling it in or asking with a question card."""
    calls = []

    class Search(Dummy):
        @property
        def parameters_schema(self):
            return {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

        async def execute(self, parameters):
            calls.append(parameters)
            return {"text": "found"}

    registry = ToolRegistry()
    registry.register(Search("search_repositories", "Search repositories"))

    def script(messages, tools):
        if messages[-1]["role"] == "tool":
            return {"content": "ok", "tool_calls": []}
        return ("app__search_repositories", {})

    llm = ScriptedLLM(script)
    agent = BaseAgent(registry, {"app": True})
    agent.can_ask = True
    run(agent, "what are the repositories names?", llm)
    reply = llm.calls[-1]["messages"][-1]["content"]
    assert calls == []  # the app was never called with a broken request
    assert "query" in reply and "nexus_ask_user" in reply


def test_after_a_tool_error_the_model_may_ask_instead_of_giving_up():
    class Failing(Dummy):
        async def execute(self, parameters):
            raise RuntimeError("Not Found")

    registry = ToolRegistry()
    registry.register(Failing("get_repo", "Get a repository"))
    llm = ScriptedLLM(lambda m, t: {"content": "ok", "tool_calls": []} if m[-1]["role"] == "tool" else ("app__get_repo", {}))
    agent = BaseAgent(registry, {"app": True})
    agent.can_ask = True
    run(agent, "show the repo", llm)
    reply = llm.calls[-1]["messages"][-1]["content"]
    assert "Not Found" in reply and "nexus_ask_user" in reply


def test_conversations_can_be_renamed_and_pinned(client):
    older, newer = new_session(client), new_session(client)
    r = client.patch(f"/api/agent/sessions/{older}", json={"title": "  Trip plans  ", "pinned": True})
    assert r.status_code == 200 and r.json()["title"] == "Trip plans" and r.json()["metadata"]["pinned"] is True
    ids = [s["session_id"] for s in client.get("/api/agent/sessions").json()]
    assert ids.index(older) < ids.index(newer)  # pinned first, though older
    client.patch(f"/api/agent/sessions/{older}", json={"pinned": False})
    ids = [s["session_id"] for s in client.get("/api/agent/sessions").json()]
    assert ids.index(newer) < ids.index(older)
    assert client.patch(f"/api/agent/sessions/{older}", json={"title": "   "}).status_code == 422
    assert client.patch("/api/agent/sessions/nope", json={"title": "x"}).status_code == 404


def test_a_greeting_stays_small_even_with_apps_connected(client, llm):
    """'Hii' cost ~1,200 tokens: the whole tool protocol, the question-card tool and every app's who-am-I tool."""
    client.post("/api/agent/run", json={"message": "Hii", "session_id": new_session(client)})
    call = next(c for c in llm.calls if c["kind"] in ("tools", "stream"))
    offered = call.get("tools", [])
    assert "nexus_ask_user" not in offered and not any(t.endswith("__get_me") for t in offered)
    size = sum(len(m["content"]) for m in call["messages"]) // 4
    assert size < 300, size


def test_who_am_i_tools_only_come_with_a_request_about_apps():
    from app.agent.tool_selection import rank_tools

    tools = [("github__search_repositories", "Find GitHub repositories by name"), ("github__get_me", "Get details of the authenticated GitHub user")]
    assert rank_tools("Hii", tools, 5, min_score=1) == []
    assert "github__get_me" in rank_tools("my repositories", tools, 5, min_score=1)


@pytest.mark.parametrize("message", [
    "summarise https://blog.example.org/post-42",
    "what does www.example.org/pricing say?",
    "tl;dr example.org/docs/intro",
])
def test_a_shared_link_gets_the_page_reader_without_any_app(client, llm, message):
    client.post("/api/agent/run", json={"message": message, "session_id": new_session(client)})
    assert "web__read_page" in next(c for c in llm.calls if c["kind"] == "tools")["tools"]

"""Tool instructions travel only with tools, and repeated prompt parts are cache-friendly."""
from __future__ import annotations

from app.agent.abstract import FIND_TOOLS, BaseAgent
from app.llm.metering import _cached_tokens, _usage_tokens
from app.llm.providers.anthropic import AnthropicProvider
from tests.test_chatbot import ScriptedLLM, client, llm, new_session  # noqa: F401  (fixtures)

PROTOCOL_MARK = "Apps are already signed in"  # a line only the full tool instructions carry


def first_tools_call(llm):
    return next(c for c in llm.calls if c["kind"] == "tools")


def test_a_greeting_gets_the_short_prompt_and_only_the_tool_finder(client, llm):
    client.post("/api/agent/run", json={"message": "Hii", "session_id": new_session(client)})
    call = first_tools_call(llm)
    system = call["messages"][0]["content"]
    assert PROTOCOL_MARK not in system and FIND_TOOLS in system and "chat_echo" in system.lower()
    assert call["tools"] == [FIND_TOOLS]
    assert len(system) // 4 < 90, len(system) // 4


def test_tools_found_mid_turn_bring_the_full_instructions(client, llm):
    systems = []  # the instructions as each call saw them (the message list itself is updated in place)

    def script(messages, tools):
        systems.append(messages[0]["content"])
        if len(systems) == 1:
            return (FIND_TOOLS, {"query": "echo some text"})
        return {"content": "done", "tool_calls": []}

    llm.script = script
    client.post("/api/agent/run", json={"message": "Hii again", "session_id": new_session(client)})
    calls = [c for c in llm.calls if c["kind"] == "tools"]
    assert PROTOCOL_MARK not in systems[0]
    assert PROTOCOL_MARK in systems[1]
    assert any(t.endswith("__echo") for t in calls[1]["tools"])


def test_a_request_matching_app_tools_gets_the_full_instructions_at_once(client, llm):
    client.post("/api/agent/run", json={"message": "echo the text hello", "session_id": new_session(client)})
    assert PROTOCOL_MARK in first_tools_call(llm)["messages"][0]["content"]


def test_tools_are_sent_in_a_stable_order(client, llm):
    """The same tools in the same order keep the prompt's start identical, so providers can reuse their cache."""
    client.post("/api/agent/run", json={"message": "echo text and list items", "session_id": new_session(client)})
    names = first_tools_call(llm)["tools"]
    app_tools = [n for n in names if "__" in n]
    assert app_tools == sorted(app_tools)


def test_anthropic_marks_the_system_prompt_and_tools_as_cacheable():
    provider = AnthropicProvider(api_key="k")
    body = provider._body([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}], "", None, None,
                          tools=[{"name": "a", "input_schema": {}}, {"name": "b", "input_schema": {}}])
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][-1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in body["tools"][0]


def test_cached_tokens_are_read_from_both_usage_shapes():
    anthropic = {"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0}
    openai = {"prompt_tokens": 1000, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 768}}
    assert _usage_tokens(anthropic) == (1000, 5) and _cached_tokens(anthropic) == 900  # Anthropic counts reads apart
    assert _usage_tokens(openai) == (1000, 5) and _cached_tokens(openai) == 768

"""The agent eval's checks themselves (the real run uses a real AI provider: python -m app.agent.eval)."""
from __future__ import annotations

import asyncio

from app.agent import eval as agent_eval
from tests.test_chatbot import ScriptedLLM


def by_id(case_id):
    return next(c for c in agent_eval.load_cases() if c["id"] == case_id)


def test_cases_only_use_known_tools():
    names = {t.tool_name for t in agent_eval.catalog()} | {"nexus_ask_user"}
    for case in agent_eval.load_cases():
        expect = case["expect"]
        for name in [expect.get("first_call"), *expect.get("calls", []), *expect.get("not_calls", [])]:
            assert name is None or name in names, (case["id"], name)


def test_a_well_behaved_agent_passes():
    def good(messages, tools):
        task = next(m["content"] for m in messages if m["role"] == "user")
        if messages[-1]["role"] == "tool":
            return {"content": "Done. " + messages[-1]["content"], "tool_calls": []}
        if "my repo" in task.lower() or "my github" in task.lower():
            return ("github__get_me", {})
        return {"content": "Recursion is a function calling itself.", "tool_calls": []}

    for case_id in ("my-repos-unnamed", "general-knowledge"):
        result = asyncio.run(agent_eval.run_case(by_id(case_id), ScriptedLLM(good)))
        assert result["problems"] == [], (case_id, result)


def test_the_known_mistakes_are_caught():
    guess = ScriptedLLM(lambda m, t: {"content": "ok", "tool_calls": []} if m[-1]["role"] == "tool"
                        else ("github__search_users", {"query": "my"}))
    result = asyncio.run(agent_eval.run_case(by_id("my-repos-unnamed"), guess))
    assert any("first tool should be github__get_me" in p for p in result["problems"])
    assert any("github__search_users" in p for p in result["problems"])

    invents = ScriptedLLM(lambda m, t: {"content": "You probably lack permissions.", "tool_calls": []} if m[-1]["role"] == "tool"
                          else ("github__list_issues", {"owner": "acme", "repo": "private"}))
    result = asyncio.run(agent_eval.run_case(by_id("honest-error"), invents))
    assert result["problems"] == ['answer doesn\'t mention "not accessible"']

    approval = ScriptedLLM(lambda m, t: ("github__create_issue", {"owner": "yogesh", "repo": "nexus", "title": "Login fails on Safari"}))
    assert asyncio.run(agent_eval.run_case(by_id("create-issue-approval"), approval))["problems"] == []

"""Agent behaviour on recorded conversations: ``python -m app.agent.eval [--runs N]``.

Each case in ``tests/agent_golden/cases.jsonl`` is a message plus what a good agent does with it, mostly
mistakes Nexus has made before (guessing "my" GitHub user, tools for a greeting, inventing error causes).
The agent runs with the configured AI provider against fake apps that return fixed data, so real accounts
are never touched; only AI tokens are spent. Exit code 1 when any case fails.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

from app.agent.abstract import ASK_USER, BaseAgent
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

CASES = Path(__file__).resolve().parents[2] / "tests" / "agent_golden" / "cases.jsonl"


class FakeTool(Tool):
    def __init__(self, name: str, description: str, schema: dict[str, Any], result: Any, policy: str = "allow") -> None:
        super().__init__(name, name.split("__")[0], description)
        self._schema, self._result, self.policy = schema, result, policy

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._result, Exception):
            raise self._result
        return {"text": json.dumps(self._result), "data": self._result}


def _schema(**properties: str) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in properties.items()},
            "required": [k for k in properties if not k.startswith("_")]}


def catalog() -> list[FakeTool]:
    """Fake GitHub, Notion and Slack: enough tools to tempt wrong choices."""
    return [
        FakeTool("github__get_me", "[GitHub] Get details of the authenticated GitHub user", _schema(),
                 {"login": "yogesh", "name": "Yogesh"}),
        FakeTool("github__search_repositories", "[GitHub] Find GitHub repositories by name, description or user",
                 _schema(query="Search query, e.g. user:octocat"), {"items": [{"full_name": "yogesh/nexus"}, {"full_name": "yogesh/notes"}]}),
        FakeTool("github__search_users", "[GitHub] Find GitHub users by username", _schema(query="Username or words"),
                 {"items": [{"login": "my"}]}),
        FakeTool("github__list_issues", "[GitHub] List issues in a GitHub repository", _schema(owner="Owner", repo="Repository", _state="open or closed"),
                 RuntimeError("Resource not accessible by integration (403)")),
        FakeTool("github__create_issue", "[GitHub] Create an issue in a GitHub repository",
                 _schema(owner="Owner", repo="Repository", title="Title", _body="Body"), {"number": 7}, policy="ask"),
        FakeTool("notion__search", "[Notion] Search pages and databases in the user's Notion workspace", _schema(query="Words"),
                 {"results": [{"title": "Roadmap 2026", "id": "p1"}]}),
        FakeTool("notion__create_page", "[Notion] Create a page in Notion", _schema(parent="Parent page or database", title="Title"),
                 {"id": "p2"}, policy="ask"),
        FakeTool("slack__post_message", "[Slack] Post a message to a Slack channel", _schema(channel="Channel", text="Text"),
                 {"ok": True}, policy="ask"),
    ]


def check(expect: dict[str, Any], calls: list[str], answer: str, status: str, prompt_tokens: Optional[int]) -> list[str]:
    """What went wrong, as readable lines (empty when the case passed)."""
    problems = []
    app_calls = [c for c in calls if "__" in c]
    if expect.get("no_tools") and app_calls:
        problems.append(f"used tools for a message that needs none: {app_calls}")
    if expect.get("first_call") and (not app_calls or app_calls[0] != expect["first_call"]):
        problems.append(f"first tool should be {expect['first_call']}, was {app_calls[0] if app_calls else 'none'}")
    for name in expect.get("calls", []):
        if name not in calls:
            problems.append(f"never called {name}")
    for name in expect.get("not_calls", []):
        if name in calls:
            problems.append(f"called {name}, which it shouldn't")
    if expect.get("asks") and ASK_USER not in calls:
        problems.append("should have asked a question first")
    if expect.get("answer_contains") and expect["answer_contains"].lower() not in answer.lower():
        problems.append(f"answer doesn't mention \"{expect['answer_contains']}\"")
    limit = expect.get("max_prompt_tokens")
    if limit and prompt_tokens and prompt_tokens > limit:
        problems.append(f"first prompt used {prompt_tokens} tokens (limit {limit})")
    return problems


async def run_case(case: dict[str, Any], llm: Any) -> dict[str, Any]:
    from app.llm.metering import usage_scope

    registry = ToolRegistry()
    for tool in catalog():
        registry.register(tool)
    agent = BaseAgent(registry, {"github": True, "notion": True, "slack": True})
    agent.can_ask = True
    with usage_scope() as records:
        result = await agent.run(task=case["message"], llm_provider=llm, available_tools=registry.list_tool_names(), history=[])
    calls = [e["tool_name"] for e in result["events"] if e.get("type") in ("tool_executed", "tool_error") and e.get("tool_name")]
    if result.get("pending_action"):
        calls.append(result["pending_action"]["tool"])
    if result.get("status") == "needs_input":
        calls.append(ASK_USER)
    answer = result.get("response") or result.get("message") or ""
    prompt_tokens = records[0]["input"] if records else None
    return {"id": case["id"], "calls": calls, "answer": answer,
            "problems": check(case.get("expect", {}), calls, answer, result.get("status", ""), prompt_tokens)}


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main(runs: int) -> int:
    from app.core.database import init_db
    from app.llm.utils import get_default_llm_provider

    init_db()
    llm, config = get_default_llm_provider()
    if llm is None:
        print("No AI provider configured: add one in Settings > AI first.")
        return 2
    print(f"Agent eval with {config.get('provider_name')} · {config.get('model')}, {runs} run(s) per case\n")
    failed = 0
    for case in load_cases():
        results = [await run_case(case, llm) for _ in range(runs)]
        bad = [r for r in results if r["problems"]]
        failed += bool(bad)
        print(f"{'PASS' if not bad else 'FAIL'}  {case['id']:<24} {len(results) - len(bad)}/{len(results)}")
        for r in bad[:1]:
            for problem in r["problems"]:
                print(f"        - {problem}")
            print(f"        tools: {r['calls'] or 'none'}")
    print(f"\n{len(load_cases()) - failed}/{len(load_cases())} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=1, help="run each case this many times (models vary)")
    sys.exit(asyncio.run(main(parser.parse_args().runs)))

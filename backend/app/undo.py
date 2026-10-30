"""Undo an action the user approved in chat: the AI proposes the reverse call, the user confirms, Nexus runs it."""
from __future__ import annotations

import json
import re
from typing import Any

from app.llm.utils import get_default_llm_provider
from app.mcp import server_availability
from app.tools import get_tool_registry

PROMPT = ("You reverse actions in the user's apps. Reply with ONLY JSON: {\"tool\": str, \"arguments\": {...}, "
          "\"explanation\": str} for the single call that undoes the action, using a tool from the list and ids from "
          "the result, or {\"impossible\": \"<why, in one sentence>\"} when it can't be undone (a sent message, a "
          "payment, a deletion with no restore). The explanation says in plain words what the call will do.")


def _same_app(tool_name: str, app_id: str):
    try:
        tool = get_tool_registry().get_tool(tool_name)
    except Exception:
        raise ValueError(f"'{tool_name}' isn't one of your tools")
    if tool.app_id != app_id:
        raise ValueError(f"'{tool_name}' belongs to a different app than the action being undone")
    return tool


async def plan_undo(entry: dict[str, Any]) -> dict[str, Any]:
    """The call that reverses an ``action_approved`` entry. Raises ValueError when there is none."""
    meta = entry["metadata"]
    provider, _ = get_default_llm_provider()
    if provider is None:
        raise ValueError("No LLM provider configured. Add one in Settings > AI.")
    tools = "\n".join(
        f"- {t.tool_name}({', '.join((t.parameters_schema.get('properties') or {}).keys())}): {t.description[:120]}"
        for t in get_tool_registry().get_available_tools() if t.app_id == meta.get("app_id")
    )
    action = (f"The action: {meta.get('tool')}({json.dumps(meta.get('arguments') or {}, default=str)})\n"
              f"Its result: {meta.get('result') or '(none)'}\n\nTools of that app:\n{tools or '(none)'}")
    reply = (await provider.chat(messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": action}])).get("content", "")
    match = re.search(r"\{.*\}", reply or "", re.DOTALL)
    try:
        plan = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        plan = None
    if not isinstance(plan, dict):
        raise ValueError("The AI didn't propose a way to undo this")
    if plan.get("impossible"):
        raise ValueError(f"This can't be undone: {plan['impossible']}")
    tool_name, arguments = str(plan.get("tool") or ""), plan.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("The AI's undo has invalid arguments")
    _same_app(tool_name, meta.get("app_id"))
    return {"tool": tool_name, "arguments": arguments, "explanation": str(plan.get("explanation") or "")}


async def run_undo(entry: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the confirmed reverse call. Raises ValueError (wrong app) or PermissionError (app not connected).

    The arguments go to the tool exactly as confirmed: no template rendering, and empty values (clearing a field
    back to how it was) are kept."""
    from app.auth.owner import owns_app

    tool = _same_app(tool_name, entry["metadata"].get("app_id"))
    if not owns_app(tool.app_id) or not server_availability().get(tool.app_id, False):
        raise PermissionError(f"App '{tool.app_id}' is not connected")
    result = await tool.execute(arguments)
    return result if isinstance(result, dict) else {"result": result}

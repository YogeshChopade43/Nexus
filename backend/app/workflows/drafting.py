"""Draft a workflow from a plain-language description with the configured LLM."""
from __future__ import annotations

import json
import re
from typing import Any

from app.api.routes.settings import user_timezone
from app.llm.utils import get_default_llm_provider
from app.tools import get_tool_registry
from app.workflows.engine import validate_workflow

MAX_ATTEMPTS = 2
MAX_TOOLS_IN_PROMPT = 80

FORMAT = """Reply with ONLY a JSON object: {"name": str, "description": str, "nodes": [...], "edges": [...]}.
Each node: {"id": "<type>_<n>", "type": <type>, "name": str, "config": {...}}. Each edge: {"source": id, "target": id};
an edge leaving a condition also has "sourceHandle": "true" or "false".
Exactly one node has type "trigger"; its config.trigger_type is one of:
- "manual" (optional "inputs": [{"name", "type": "text|number|boolean", "required"}]) -> {{ trigger.inputs.<name> }}
- "recurrence" ("frequency": minute|hour|day|week|month, "interval", "at": "HH:MM", "weekdays": ["mon",...], "month_day", "timezone")
- "poll" ("tool": <tool name>, "parameters": {...}, "interval_minutes") -> each new item is {{ trigger.item }}
- "webhook" -> {{ trigger.payload }}
Step types and config:
- "action": {"tool": <tool name from the list>, "parameters": {...}} -> output .text and .data
- "llm": {"prompt": str} -> output .text
- "condition": {"field": "steps.<id>.data.x", "operator": truthy|falsy|equals|not_equals|contains|gt|lt|is_empty|not_empty, "value"}
- "transform": {"template": str} -> output .value
- "http": {"method", "url", "headers": {}, "body": {}} -> output .status and .data
- "code": {"code": "JavaScript function body using `input` (input.steps, input.trigger); return a value"} -> .value
- "loop": {"items": "{{ steps.<id>.data.items }}", "body": {"nodes": [...], "edges": [...]}} -> {{ loop.item }} inside
- "delay": {"seconds": n}
Reference earlier data with Jinja: {{ steps.<node id>.<field> }}. Use only tools from the list."""


def _tool_list() -> str:
    lines = []
    for tool in get_tool_registry().get_available_tools()[:MAX_TOOLS_IN_PROMPT]:
        params = ", ".join((tool.parameters_schema.get("properties") or {}).keys())
        lines.append(f"- {tool.tool_name}({params}): {tool.description[:120]}")
    return "\n".join(lines) or "(no app tools connected; use built-in steps only)"


def _parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("The AI did not return a JSON workflow")
    data = json.loads(match.group(0))
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError("The AI's workflow has no nodes")
    data.setdefault("edges", [])
    for index, edge in enumerate(data["edges"]):
        edge.setdefault("id", f"edge-{index + 1}")
    return data


async def draft_workflow(description: str) -> dict[str, Any]:
    provider, _ = get_default_llm_provider()
    if provider is None:
        raise ValueError("No LLM provider configured. Add one in Settings > AI.")
    messages = [
        {"role": "system", "content": f"You design automation workflows for Nexus.\n{FORMAT}\n\n"
                                      f"The user's timezone is {user_timezone()}: use it for schedules unless they name another. "
                                      "To remind or alert the user, use the nexus__notify tool.\n\n"
                                      f"Available tools:\n{_tool_list()}"},
        {"role": "user", "content": description},
    ]
    problem = ""
    for _ in range(MAX_ATTEMPTS):
        reply = (await provider.chat(messages=messages)).get("content", "")
        try:
            draft = _parse(reply)
            errors, warnings = validate_workflow(draft["nodes"], draft["edges"], get_tool_registry())
            if not errors:
                return {"name": draft.get("name") or "Drafted workflow", "description": draft.get("description") or description,
                        "nodes": draft["nodes"], "edges": draft["edges"], "warnings": warnings}
            problem = "; ".join(errors)
        except (ValueError, json.JSONDecodeError) as exc:
            problem = str(exc)
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"That was not valid ({problem}). Reply with only the corrected JSON."}]
    raise ValueError(f"Could not draft a valid workflow: {problem}")

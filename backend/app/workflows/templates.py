"""Ready-made workflows. They use only built-in steps so they work without any MCP server."""
from __future__ import annotations

from typing import Any


def _chain(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"nodes": list(nodes), "edges": [
        {"id": f"edge-{a['id']}-{b['id']}", "source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:])
    ]}


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "daily-briefing",
        "name": "Daily AI briefing",
        "description": "Every weekday morning, ask the AI for a short plan for the day.",
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
                "trigger_type": "recurrence", "frequency": "week", "interval": 1, "at": "08:30",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"], "timezone": "UTC"}},
            {"id": "llm_1", "type": "llm", "name": "Plan my day", "config": {
                "prompt": "Today is {{ trigger.fired_at }}. Give me three focused priorities and one tip for a productive day."}},
        ),
    },
    {
        "id": "summarize-webhook",
        "name": "Summarize incoming webhooks",
        "description": "When another system calls the webhook URL, summarize the payload with AI.",
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {"trigger_type": "webhook"}},
            {"id": "llm_1", "type": "llm", "name": "Summarize", "config": {
                "prompt": "Summarize this event in two sentences for a busy engineer:\n{{ trigger.payload | tojson }}"}},
        ),
    },
    {
        "id": "ask-and-post",
        "name": "Ask AI and post the answer",
        "description": "Run it with a question; the AI answers and the answer is POSTed to a URL you choose.",
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
                "trigger_type": "manual", "inputs": [
                    {"name": "question", "type": "text", "required": True, "default": None},
                    {"name": "post_url", "type": "text", "required": True, "default": None},
                ]}},
            {"id": "llm_1", "type": "llm", "name": "Answer", "config": {"prompt": "{{ trigger.inputs.question }}"}},
            {"id": "http_1", "type": "http", "name": "Post answer", "config": {
                "method": "POST", "url": "{{ trigger.inputs.post_url }}", "body": {"answer": "{{ steps.llm_1.text }}"}}},
        ),
    },
    {
        "id": "each-item",
        "name": "Process each item of a list",
        "description": "Loop over a list and let the AI write one line per item.",
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
                "trigger_type": "manual", "inputs": [{"name": "items", "type": "text", "required": True, "default": "apples, mangoes, kiwis"}]}},
            {"id": "code_1", "type": "code", "name": "Split list", "config": {
                "code": "return input.trigger.inputs.items.split(',').map(s => s.trim()).filter(Boolean);"}},
            {"id": "loop_1", "type": "loop", "name": "For each item", "config": {
                "items": "{{ steps.code_1.value }}",
                "body": _chain({"id": "llm_1", "type": "llm", "name": "One line", "config": {
                    "prompt": "Write one fun sentence about {{ loop.item }}."}})}},
        ),
    },
]


def get_template(template_id: str) -> dict[str, Any] | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)

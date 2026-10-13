"""Ready-made workflows. They use only built-in steps; ``needs`` names what to connect first, if anything."""
from __future__ import annotations

from typing import Any


def _chain(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"nodes": list(nodes), "edges": [
        {"id": f"edge-{a['id']}-{b['id']}", "source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:])
    ]}


def _weekdays(at: str) -> dict[str, Any]:
    return {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
        "trigger_type": "recurrence", "frequency": "week", "interval": 1, "at": at,
        "weekdays": ["mon", "tue", "wed", "thu", "fri"]}}


def _ask(node_id: str, name: str, prompt: str) -> dict[str, Any]:
    """The agent with the user's apps, read-only (see nexus__ask_agent)."""
    return {"id": node_id, "type": "action", "name": name, "config": {"tool": "nexus__ask_agent", "parameters": {"prompt": prompt}}}


def _notify(title: str, message: str) -> dict[str, Any]:
    return {"id": "notify_1", "type": "action", "name": "Send it",
            "config": {"tool": "nexus__notify", "parameters": {"title": title, "message": message}}}


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "daily-briefing",
        "name": "Morning briefing",
        "description": "Every weekday at 8, a short summary of your meetings, important email and app updates, sent to your phone.",
        "needs": [],
        **_chain(
            _weekdays("08:00"),
            _ask("brief", "Write the briefing", "Prepare my morning briefing from my connected apps (read only): today's "
                 "meetings, important unread email, and what needs my attention in my apps. Short: a heading per section, "
                 "bullets, most important first; leave out empty sections."),
            _notify("Your morning briefing", "{{ steps.brief.text }}"),
        ),
    },
    {
        "id": "inbox-triage",
        "name": "Inbox triage",
        "description": "Every weekday at 9, sort unread email into needs a reply / FYI / ignore and save draft replies (nothing is sent).",
        "needs": ["Email"],
        **_chain(
            _weekdays("09:00"),
            _ask("triage", "Triage the inbox", "Look at my unread email from the last day. Sort it into: needs a reply, FYI, "
                 "and can ignore (newsletters, notifications). For each that needs a reply, save a short, polite draft reply "
                 "in my drafts (don't send anything). Then list the three groups briefly."),
            _notify("Inbox triaged", "{{ steps.triage.text }}"),
        ),
    },
    {
        "id": "daily-reminder",
        "name": "Daily reminder",
        "description": "A reminder at the same time every day, in the bell and on your phone. Change the time and the words.",
        "needs": [],
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
                "trigger_type": "recurrence", "frequency": "day", "interval": 1, "at": "21:00"}},
            _notify("Take your medicines", "Time for your evening dose."),
        ),
    },
    {
        "id": "weekly-report-doc",
        "name": "Weekly report as a Word document",
        "description": "Every Friday at 5, a report of the week from your apps, saved as a .docx you can download.",
        "needs": [],
        **_chain(
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {
                "trigger_type": "recurrence", "frequency": "week", "interval": 1, "at": "17:00", "weekdays": ["fri"]}},
            _ask("report", "Write and save the report", "Write my weekly report from my connected apps (read only): what got "
                 "done, what's in progress, what's blocked, and next week's priorities. Save it with files__create_file as "
                 "weekly-report.docx, using Markdown headings and bullets, then say it's ready."),
            _notify("Your weekly report is ready", "{{ steps.report.text }}"),
        ),
    },
    {
        "id": "web-news",
        "name": "News on a topic",
        "description": "Every morning, the web's most important news on a topic you choose, in three bullets.",
        "needs": ["Web search"],
        **_chain(
            _weekdays("07:30"),
            _ask("news", "Find the news", "Search the web for the most important news from the last day about: AI agents. "
                 "Give three bullets, each with one sentence and the link."),
            _notify("Today's news", "{{ steps.news.text }}"),
        ),
    },
    {
        "id": "summarize-webhook",
        "needs": [],
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
        "needs": [],
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
        "needs": [],
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

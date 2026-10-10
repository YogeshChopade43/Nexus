"""Facts the agent remembers across chats, and registration of Nexus's built-in tools.

Document search lives in ``app.rag``; its tool is registered here alongside the memory tools so all
``nexus__`` tools appear in one place.
"""
from __future__ import annotations

import json
import re

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.database import get_connection, log_activity
from app.tools.base import Tool

APP_ID = "nexus"
MAX_MEMORIES = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def list_memories() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM memories ORDER BY id").fetchall()]
    finally:
        conn.close()


def add_memory(content: str) -> dict[str, Any]:
    content = " ".join(content.split())[:500]
    if not content:
        raise ValueError("Nothing to remember")
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM memories WHERE lower(content) = lower(?)", (content,)).fetchone()
        if existing:
            return dict(existing)
        if conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] >= MAX_MEMORIES:
            raise ValueError(f"Memory is full ({MAX_MEMORIES} facts). Remove some in Knowledge > Memory.")
        cursor = conn.execute("INSERT INTO memories (content, created_at) VALUES (?, ?)", (content, _now()))
        conn.commit()
        return dict(conn.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone())
    finally:
        conn.close()


def delete_memory(memory_id: int) -> bool:
    conn = get_connection()
    try:
        deleted = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


def memory_prompt() -> str:
    """Remembered facts for the system prompt, with ids so the agent can forget one."""
    memories = list_memories()
    if not memories:
        return ""
    lines = "\n".join(f"- [{m['id']}] {m['content']}" for m in memories)
    return f"## Things the user asked you to remember\n{lines}"


class _BuiltIn(Tool):
    policy = "allow"
    read_only: bool = True

    def __init__(self, name: str, description: str, schema: dict[str, Any]) -> None:
        super().__init__(f"{APP_ID}__{name}", APP_ID, description)
        self._schema = schema

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema


class Remember(_BuiltIn):
    read_only = False

    def __init__(self) -> None:
        super().__init__("remember", "Save a fact the user wants you to remember in future conversations "
                         "(preferences, names, IDs). Only when the user asks you to remember something.", {
            "type": "object",
            "properties": {"fact": {"type": "string", "description": "The fact, as one short sentence"}},
            "required": ["fact"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        memory = add_memory(str(parameters.get("fact") or ""))
        return {"text": f"Remembered (#{memory['id']}): {memory['content']}", "data": memory}


class Forget(_BuiltIn):
    read_only = False

    def __init__(self) -> None:
        super().__init__("forget", "Delete a remembered fact by its number when the user asks you to forget it.", {
            "type": "object",
            "properties": {"memory_id": {"type": "integer", "description": "The number shown in [brackets]"}},
            "required": ["memory_id"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        ok = delete_memory(int(parameters.get("memory_id") or 0))
        return {"text": "Forgotten." if ok else "There is no memory with that number.", "data": {"deleted": ok}}


class Notify(_BuiltIn):
    """A workflow step that alerts the user: the bell, and a browser notification while Nexus is open."""
    read_only = False

    def __init__(self) -> None:
        super().__init__("notify", "Notify the user: shows in Nexus's notification bell and as a browser "
                         "notification while Nexus is open. Use for reminders and alerts in workflows.", {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Short headline, e.g. 'Take your medicines'"},
                           "message": {"type": "string", "description": "Optional details"}},
            "required": ["title"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        title = str(parameters.get("title") or "Reminder")[:200]
        log_activity("reminder", title, str(parameters.get("message") or "")[:1000])
        return {"text": f"Notified: {title}", "data": {"title": title}}


async def alert_channel_missing(llm: Any, task: str, description: str) -> bool:
    """Does this workflow alert the user without saying where? The model reads the request (any wording or
    language) instead of keyword lists. An unreadable answer counts as missing: asking beats guessing."""
    prompt = (f"The user asked: {task}\nThe workflow to create: {description}\n\n"
              "Does this workflow alert or remind the user? If it does, does the request say where the alert should "
              "reach them (for example a pop-up, email, a chat app or their phone)? Reply with only JSON: "
              '{"alerts_user": true or false, "says_where": true or false}')
    try:
        reply = await llm.chat(messages=[{"role": "system", "content": "You classify requests. Reply with JSON only."},
                                         {"role": "user", "content": prompt}])
        found = re.search(r"\{.*\}", reply.get("content") or "", re.DOTALL)
        verdict = json.loads(found.group(0)) if found else None
    except Exception:  # no answer, or not JSON
        verdict = None
    if not isinstance(verdict, dict):
        return True
    return bool(verdict.get("alerts_user")) and not bool(verdict.get("says_where"))


class CreateWorkflow(_BuiltIn):
    """Turns "remind me every day at 9" in chat into a scheduled workflow. Asks first: it adds an automation."""
    read_only = False
    policy = "ask"

    def __init__(self) -> None:
        super().__init__("create_workflow", "Create and switch on an automation from a plain-language description: "
                         "reminders, schedules ('every weekday at 9am') or app automations. The user approves it first.", {
            "type": "object",
            "properties": {"description": {"type": "string", "description": "What should happen and when, in the "
                                           "user's words, e.g. 'Every day at 11:57 pm, remind me to take my medicines'"}},
            "required": ["description"],
        })

    async def precheck(self, arguments: dict[str, Any], context: dict[str, Any]) -> Optional[str]:
        """Before the approval card: a reminder whose alert channel nobody chose goes back to the agent to ask."""
        if context["asked"]:
            return None
        if not await alert_channel_missing(context["llm"], context["task"], str(arguments.get("description") or "")):
            return None
        options = ["'Nexus pop-up' (the notification bell, plus a desktop pop-up while Nexus is open)"]
        options += [f"'{app.replace('_', ' ').title()}'" for app in context["apps"]]
        return ("Not created yet: ask the user where the alert should reach them first, with nexus_ask_user "
                f"(header 'Alerts'). Options: {', '.join(options)}; they can also type their own. Then call "
                "create_workflow again with their choice written into the description.")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.api.routes.workflows import create_workflow
        from app.models.workflow import WorkflowCreate
        from app.workflows import drafting
        from app.workflows.scheduler import next_run_time

        draft = await drafting.draft_workflow(str(parameters.get("description") or "").strip())
        workflow = create_workflow(WorkflowCreate(name=draft["name"], description=draft["description"],
                                                  nodes=draft["nodes"], edges=draft["edges"], isActive=True))
        next_run = next_run_time(workflow.id)
        text = (f"Created and switched on the workflow '{workflow.name}'."
                + (f" Next run: {next_run}." if next_run else "") + " It's on the Workflows page, where it can be changed.")
        return {"text": text, "data": {"workflow_id": workflow.id, "name": workflow.name, "next_run_at": next_run}}


def register_builtin_tools(registry) -> None:
    from app.rag.tool import SearchDocuments

    for tool in (SearchDocuments(), Remember(), Forget(), Notify(), CreateWorkflow()):
        registry.register(tool)

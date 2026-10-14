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


def _owner() -> int:
    from app.auth.owner import owner_id

    return owner_id()


def list_memories() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM memories WHERE user_id = ? ORDER BY id", (_owner(),)).fetchall()]
    finally:
        conn.close()


def add_memory(content: str, source: str = "manual") -> dict[str, Any]:
    content = " ".join(content.split())[:500]
    if not content:
        raise ValueError("Nothing to remember")
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM memories WHERE lower(content) = lower(?) AND user_id = ?", (content, _owner())).fetchone()
        if existing:
            return dict(existing)
        if conn.execute("SELECT COUNT(*) FROM memories WHERE user_id = ?", (_owner(),)).fetchone()[0] >= MAX_MEMORIES:
            raise ValueError(f"Memory is full ({MAX_MEMORIES} facts). Remove some in Knowledge > Memory.")
        cursor = conn.execute("INSERT INTO memories (content, created_at, source, user_id) VALUES (?, ?, ?, ?)",
                              (content, _now(), source, _owner()))
        conn.commit()
        return dict(conn.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone())
    finally:
        conn.close()


def delete_memory(memory_id: int) -> bool:
    conn = get_connection()
    try:
        deleted = conn.execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, _owner())).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


LEARN_EVERY = 3  # user messages between automatic memory updates (each costs one short AI call)
_learning: set = set()  # running background tasks (kept so they aren't garbage-collected)


def learn_later(session_id: str) -> None:
    """Every few messages, in the background: save lasting facts the user stated (unless switched off)."""
    import asyncio

    from app.agent.sessions import get_session
    from app.api.routes.settings import load_user_settings

    if not (load_user_settings().get("memory") or {}).get("auto", True):
        return
    messages = (get_session(session_id) or {}).get("messages") or []
    if sum(1 for m in messages if m.get("role") == "user") % LEARN_EVERY != 0:
        return
    try:
        task = asyncio.get_running_loop().create_task(learn_from(messages[-2 * LEARN_EVERY:]))
    except RuntimeError:  # no event loop: nothing to run it on
        return
    _learning.add(task)
    task.add_done_callback(_learning.discard)


async def learn_from(messages: list[dict[str, Any]]) -> list[str]:
    from app.api.routes import agent as agent_route  # the same AI provider as the chat

    llm, _ = agent_route.get_default_llm_provider()
    if llm is None:
        return []
    known = "\n".join(f"- {m['content']}" for m in list_memories()) or "(nothing yet)"
    talk = "\n".join(f"{m['role']}: {str(m.get('content') or '')[:600]}" for m in messages)
    prompt = (f"Already remembered:\n{known}\n\nRecent conversation:\n{talk}\n\n"
              "List new facts worth remembering about the user for future chats: lasting preferences, names, "
              "accounts, IDs, how they like things done. Only what the user said or confirmed; nothing one-off, "
              "nothing already remembered. Each as one short sentence. Reply with only a JSON list of strings, "
              "at most 3; [] if none.")
    try:
        reply = await llm.chat(messages=[{"role": "system", "content": "You keep a user's long-term memory. JSON only."},
                                         {"role": "user", "content": prompt}])
        found = re.search(r"\[.*\]", reply.get("content") or "", re.DOTALL)
        facts = json.loads(found.group(0)) if found else []
    except Exception:  # memory is a bonus: never break or slow the chat
        return []
    learned = []
    known_lower = {m["content"].lower() for m in list_memories()}
    for fact in facts[:3] if isinstance(facts, list) else []:
        fact = " ".join(str(fact).split())[:500]
        if not fact or fact.lower() in known_lower:
            continue
        try:
            add_memory(fact, source="auto")
        except ValueError:  # memory full
            break
        log_activity("memory_learned", f"Remembered: {fact}", "Learned from a chat. Remove it in Knowledge > Memory.")
        learned.append(fact)
    return learned


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
        super().__init__("notify", "Notify the user: Nexus's notification bell, a browser notification while Nexus "
                         "is open, and their phone when Telegram is linked. Use for reminders and alerts in workflows.", {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Short headline, e.g. 'Take your medicines'"},
                           "message": {"type": "string", "description": "Optional details"}},
            "required": ["title"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.workflows.scheduler import due_note  # a reminder that ran late says when it was due

        title = str(parameters.get("title") or "Reminder")[:200] + due_note()
        message = str(parameters.get("message") or "")[:4000]  # room for a daily briefing
        log_activity("reminder", title, message)
        from app.integrations.telegram import notify_all  # and on the phone, when Telegram is linked

        await notify_all(title, message)
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
        super().__init__("create_workflow", "Create and switch on a NEW automation from a plain-language description: "
                         "reminders, schedules ('every weekday at 9am') or app automations. The user approves it first. "
                         "To change, pause or delete an existing one, use nexus__change_workflow instead.", {
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


def _find_workflow(ref: str) -> dict[str, Any]:
    """A workflow by number, exact name, or a part of its name that only one workflow has."""
    conn = get_connection()
    try:
        from app.auth.owner import owner_id

        rows = [dict(r) for r in conn.execute("SELECT id, name FROM workflows WHERE user_id = ? ORDER BY id",
                                              (owner_id(),)).fetchall()]
    finally:
        conn.close()
    ref = ref.strip().lstrip("#")
    wanted = ref.lower()
    matches = ([r for r in rows if str(r["id"]) == ref] or [r for r in rows if r["name"].lower() == wanted]
               or [r for r in rows if wanted and wanted in r["name"].lower()])
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No workflow matches '{ref}'. Use nexus__list_workflows to see them.")
    raise ValueError(f"'{ref}' matches several workflows: " + ", ".join(f"#{r['id']} {r['name']}" for r in matches)
                     + ". Ask the user which one.")


class ListWorkflows(_BuiltIn):
    def __init__(self) -> None:
        super().__init__("list_workflows", "List the user's workflows and reminders: number, name, active or stopped, "
                         "what it does, next run and how the last run went.", {"type": "object", "properties": {}})

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.api.routes.workflows import list_workflows

        workflows = list_workflows(limit=500, offset=0)
        if not workflows:
            return {"text": "The user has no workflows yet.", "data": {"workflows": []}}
        lines = []
        for w in workflows:
            next_run = (w.trigger_config or {}).get("next_run_at")
            automatic = (w.trigger_config or {}).get("type", "manual") != "manual"
            state = ("active" if w.isActive else "stopped") if automatic else ("manual: runs only when started"
                                                                               if w.isActive else "disabled")
            lines.append(f"#{w.id} {w.name} ({state}): {w.description or 'no description'}"
                         + (f" Next run: {next_run}." if next_run and w.isActive else "")
                         + (f" Last run: {w.last_status}." if w.last_status else ""))
        return {"text": "\n".join(lines), "data": {"workflows": [{"id": w.id, "name": w.name, "active": w.isActive}
                                                                for w in workflows]}}


class ChangeWorkflow(_BuiltIn):
    """Pause, resume, change or delete an existing workflow from chat. Asks first: it changes an automation."""
    read_only = False
    policy = "ask"

    def __init__(self) -> None:
        super().__init__("change_workflow", "Change an EXISTING workflow or reminder: stop it (pause), start it again (resume), delete it, "
                         "or edit it (new time, new message, other steps). Find it with nexus__list_workflows first.", {
            "type": "object",
            "properties": {
                "workflow": {"type": "string", "description": "The workflow's name, or its #number"},
                "action": {"type": "string", "enum": ["pause", "resume", "edit", "delete"]},
                "change": {"type": "string", "description": "For edit: what to change, in the user's words, "
                                                            "e.g. 'move it to 3 pm on weekdays'"},
            },
            "required": ["workflow", "action"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.api.routes.workflows import delete_workflow, get_workflow, update_workflow
        from app.models.workflow import WorkflowUpdate
        from app.workflows import drafting
        from app.workflows.scheduler import next_run_time

        found = _find_workflow(str(parameters.get("workflow") or ""))
        action, name = parameters.get("action"), found["name"]
        if action == "delete":
            delete_workflow(found["id"])
            return {"text": f"Deleted the workflow '{name}'.", "data": {"workflow_id": found["id"], "deleted": True}}
        if action in ("pause", "resume"):
            update_workflow(found["id"], WorkflowUpdate(isActive=action == "resume"))
            text = f"{'Started' if action == 'resume' else 'Stopped'} the workflow '{name}'."
        elif action == "edit":
            change = str(parameters.get("change") or "").strip()
            if not change:
                raise ValueError("Say what to change in 'change', e.g. 'move it to 3 pm'.")
            current = get_workflow(found["id"])
            draft = await drafting.draft_workflow(change, current={
                "name": current.name, "description": current.description, "nodes": current.nodes, "edges": current.edges})
            updated = update_workflow(found["id"], WorkflowUpdate(name=draft["name"], description=draft["description"],
                                                                  nodes=draft["nodes"], edges=draft["edges"]))
            text = f"Changed the workflow '{updated.name}': {updated.description}."
        else:
            raise ValueError("action must be pause, resume, edit or delete")
        next_run = next_run_time(found["id"])
        return {"text": text + (f" Next run: {next_run}." if next_run else ""),
                "data": {"workflow_id": found["id"], "next_run_at": next_run}}


class AskAgent(_BuiltIn):
    """A workflow step that runs the agent with the user's apps, read-only, and returns its answer."""

    def __init__(self) -> None:
        super().__init__("ask_agent", "Run the Nexus agent on a request, using the user's connected apps to look "
                         "things up (read-only: it changes and sends nothing), and return its answer. For workflow "
                         "steps such as a daily briefing, a digest or a summary.", {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "What the agent should find out or write"}},
            "required": ["prompt"],
        })

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.api.routes.agent import run_unattended

        answer = await run_unattended(str(parameters.get("prompt") or "").strip())
        return {"text": answer, "data": {"answer": answer}}


def register_builtin_tools(registry) -> None:
    from app.rag.tool import SearchDocuments

    for tool in (SearchDocuments(), Remember(), Forget(), Notify(), CreateWorkflow(), ListWorkflows(), ChangeWorkflow(),
                 AskAgent()):
        registry.register(tool)
    from app.integrations.files_tool import CreateFile  # under the app "files": offered when a request is about making a file

    registry.register(CreateFile())

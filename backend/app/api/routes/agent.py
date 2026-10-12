from __future__ import annotations

import json
import re
import logging
import asyncio
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agent.sessions import (
    append_message,
    create_session,
    delete_session,
    update_session,
    get_history,
    get_session,
    list_sessions,
    replace_messages,
    set_metadata,
)
from app.agent.abstract import BaseAgent, clean_history
from app import knowledge
from app.core.database import log_activity
from app.knowledge import APP_ID as BUILTIN_APP
from app.rag.answer import sources_block
from app.rag.models import DEFAULT_WORKSPACE
from app.rag.retrieve import retrieve
from app.rag.tool import has_readable_documents, rag_turn, readable_document_names
from app.llm.metering import usage_scope, usage_total
from app.mcp import server_states, store
from app.llm.utils import get_active_llm_provider, get_default_llm_provider
from app.models.agent import (
    AgentRunRequest,
    AgentRunResponse,
    AgentSessionCreate,
    AgentSession,
    SessionPatch,
    AnswerRequest, ApprovalRequest,
    ChatSettings,
)
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _app_label(app_id: str) -> str:
    return app_id.capitalize()


def _resolve_llm_provider(req: AgentRunRequest):
    """The requested provider, else the default enabled one, else None."""
    try:
        if req.llm_provider_id:
            provider, _config = get_active_llm_provider(provider_id=req.llm_provider_id)
            return provider
        provider, _config = get_default_llm_provider()
        return provider
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"LLM provider error: {exc}")


def _session_history(session_id: str | None, req: AgentRunRequest) -> list[dict[str, Any]]:
    if session_id:
        return clean_history(get_history(session_id, limit=20))
    return clean_history(req.context.get("previousMessages", []))


def _build_available_tools(req: AgentRunRequest, tool_registry, states):
    all_tools = tool_registry.get_available_tools()
    known_tool_names = {tool.tool_name for tool in all_tools}
    tools_by_name = {tool.tool_name: tool for tool in all_tools}

    requested_names = req.available_tools
    if requested_names:
        requested_known = [name for name in requested_names if name in known_tool_names]
        available_names = {
            name
            for name in requested_known
            if states.get(tools_by_name[name].app_id, {}).get("available", False)
        }
        unavailable_names = set(requested_known) - available_names
        available_tools = [name for name in requested_names if name in available_names]
    else:
        available_names = {
            tool.tool_name
            for tool in all_tools
            if states.get(tool.app_id, {}).get("available", False)
        }
        unavailable_names = set()
        available_tools = [tool.tool_name for tool in all_tools if tool.tool_name in available_names]

    return available_tools, unavailable_names, tools_by_name, states


def _augment_with_unavailable_apps(result, task, unavailable_names, tools_by_name, states):
    task_lower = (task or "").lower()
    unavailable_apps = {
        tools_by_name[name].app_id
        for name in unavailable_names
        if name in tools_by_name
    }
    for app_id, state in states.items():
        if state.get("available"):
            continue
        app = next((item for item in tools_by_name.values() if item.app_id == app_id), None)
        if app is None:
            continue
        if app_id in task_lower or app.app_id in task_lower:
            unavailable_apps.add(app_id)

    if unavailable_apps:
        messages = []
        for app_id in sorted(unavailable_apps):
            state = states.get(app_id, {})
            reason = "disabled" if not state.get("enabled", False) else "not connected"
            messages.append(f"The {app_id} MCP server is {reason}. Check it on the MCP Servers page.")
        result["message"] = " ".join([result.get("message", ""), *messages]).strip()
        result["response"] = result["message"]
        existing_apps = {
            event.get("app_id")
            for event in result.get("events", [])
            if event.get("type") == "app_unavailable"
        }
        for app_id in sorted(unavailable_apps - existing_apps):
            result["events"].append({
                "type": "app_unavailable",
                "app_id": app_id,
                "reason": "App is not available" if not states.get(app_id, {}).get("enabled", False) else "App is not connected",
            })
    return result


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/sessions")
def create_agent_session(req: AgentSessionCreate) -> AgentSession:
    session_id = create_session(title=req.title or "")
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=500, detail="Failed to create session")
    return AgentSession(**session)


@router.get("/sessions")
def list_agent_sessions(limit: int = Query(50, ge=1, le=200), q: str = "") -> list[AgentSession]:
    """Conversations, newest first; ``q`` searches titles and message text."""
    sessions = list_sessions(limit=limit, query=q.strip())
    return [AgentSession(**s) for s in sessions]


@router.get("/sessions/{session_id}")
def get_agent_session(session_id: str) -> AgentSession:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return AgentSession(**session)


@router.patch("/sessions/{session_id}")
def update_agent_session(session_id: str, body: SessionPatch) -> AgentSession:
    """Rename or pin a conversation (pinned ones are listed first)."""
    if not update_session(session_id, title=body.title, pinned=body.pinned):
        raise HTTPException(status_code=404, detail="Session not found")
    return AgentSession(**get_session(session_id))


@router.delete("/sessions/{session_id}")
def delete_agent_session(session_id: str) -> dict[str, Any]:
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "deleted": True}


# ---------------------------------------------------------------------------
# Agent run (non-streaming)
# ---------------------------------------------------------------------------

MAX_ATTACHMENT_CHARS = 100_000
HISTORY_KEEP = 20  # recent messages sent as-is; older ones are summarized
SUMMARY_EVERY = 10  # re-summarize once this many more messages have scrolled out of the window


def _task_with_attachments(req: AgentRunRequest) -> str:
    task = req.task or req.message or ""
    for attachment in req.attachments:
        content = attachment.content
        if len(content) > MAX_ATTACHMENT_CHARS:
            content = content[:MAX_ATTACHMENT_CHARS] + "\n... [file truncated]"
        task += f"\n\nAttached file '{attachment.name}':\n```\n{content}\n```"
    return task


def _chat_settings(session: dict[str, Any], req: AgentRunRequest) -> ChatSettings:
    """The request's settings (saved to the session), else what the session saved earlier."""
    if req.chat_settings is not None and req.session_id is not None:
        metadata = dict(session.get("metadata") or {})
        metadata["settings"] = req.chat_settings.model_dump()
        set_metadata(req.session_id, metadata)
    if req.chat_settings is not None:
        return req.chat_settings
    return ChatSettings(**((session.get("metadata") or {}).get("settings") or {}))


PAUSED = ("needs_approval", "needs_input")  # a run waiting on the user (saved with the chat)

# Messages that ask for something scheduled or automatic: only these get the create-workflow tool.
AUTOMATION_REQUEST = re.compile(
    r"\b(remind\w*|schedul\w*|automat\w*|workflows?|every (day|weekday|week|month|morning|evening|night|hour|monday|"
    r"tuesday|wednesday|thursday|friday|saturday|sunday|\d+)|daily|weekly|monthly|each (day|morning|week))\b", re.IGNORECASE)

WORKFLOW_TOOLS = {f"{BUILTIN_APP}__create_workflow", f"{BUILTIN_APP}__change_workflow"}  # can need a question card


class _Prepared:
    """Everything one agent turn needs, shared by /run, /run/stream and /approval."""

    def __init__(self, req: AgentRunRequest, session_id: Optional[str]):
        self.task = _task_with_attachments(req)
        if not self.task.strip():
            raise HTTPException(status_code=400, detail="task or message is required")
        self.req = req
        self.session_id = session_id
        self.session = (get_session(session_id) if session_id else None) or {}
        self.settings = _chat_settings(self.session, req)
        self.states = server_states()
        self.llm = _resolve_llm_provider(req)
        if self.settings.temperature is not None and hasattr(self.llm, "defaults"):  # Metered providers
            self.llm.defaults["temperature"] = self.settings.temperature
        self.registry = get_tool_registry()
        self.available, self.unavailable, self.tools_by_name, _ = _build_available_tools(req, self.registry, self.states)
        if self.settings.servers is not None:  # this chat uses only the chosen servers (plus Nexus's own tools)
            allowed = set(self.settings.servers) | {BUILTIN_APP}
            self.available = [n for n in self.available if self.tools_by_name[n].app_id in allowed]
        self.document_names = readable_document_names(DEFAULT_WORKSPACE, session_id)
        # "@Notion ..." / "@resume.pdf": the user pointed at an app (only its tools, plus Nexus's own) or a document.
        lowered = self.task.lower()
        self.mentioned_apps = [s for s in store.list_servers() if s.enabled and f"@{s.name.lower()}" in lowered]
        self.mentioned_documents = [d for d in self.document_names if f"@{d.lower()}" in lowered]
        if self.mentioned_apps:
            pointed = {s.slug for s in self.mentioned_apps} | {BUILTIN_APP}
            self.available = [n for n in self.available if self.tools_by_name[n].app_id in pointed]
        if not self.document_names:
            self.available = [n for n in self.available if n != f"{BUILTIN_APP}__search_documents"]
        # Memory tools only when asked: offering tools sends the reply down the tool-calling path,
        # which can't stream, so plain chats without servers would lose word-by-word streaming.
        self.available = [n for n in self.available if n != f"{BUILTIN_APP}__notify"]  # a workflow step, not for chat
        if not re.search(r"remember|forget|memor", self.task, re.IGNORECASE):
            self.available = [n for n in self.available if n not in (f"{BUILTIN_APP}__remember", f"{BUILTIN_APP}__forget")]
        if not AUTOMATION_REQUEST.search(self.task):  # "remind me every day at 9", "every weekday send me..."
            self.available = [n for n in self.available if n != f"{BUILTIN_APP}__create_workflow"]
        # Listing and changing workflows also follow the topic: "pause the second one" after "what reminders do I have?".
        recent = " ".join(str(m.get("content") or "") for m in (self.session.get("messages") or [])[-2:])
        if not AUTOMATION_REQUEST.search(f"{self.task} {recent}"):
            self.available = [n for n in self.available
                              if n not in (f"{BUILTIN_APP}__list_workflows", f"{BUILTIN_APP}__change_workflow")]
        self.history: list[dict[str, Any]] = []
        self.summary = ""

    async def load_history(self) -> None:
        """Recent messages, plus a running summary of older ones so long chats don't forget."""
        if not self.session_id:
            self.history = clean_history(self.req.context.get("previousMessages", []))[-HISTORY_KEEP:]
            return
        messages = clean_history(self.session.get("messages") or [])
        self.history = messages[-HISTORY_KEEP:]
        older = messages[:-HISTORY_KEEP]
        metadata = dict(self.session.get("metadata") or {})
        self.summary = metadata.get("summary", "")
        done = int(metadata.get("summary_upto") or 0)
        if not older or self.llm is None or (self.summary and len(older) - done < SUMMARY_EVERY):
            return
        transcript = "\n".join(f"{m['role']}: {m['content'][:2000]}" for m in older[done:])
        try:
            reply = await self.llm.chat(messages=[
                {"role": "system", "content": "Summarize this conversation for your own memory in under 250 words. "
                 "Keep names, IDs, numbers, decisions and open questions. Plain text."},
                {"role": "user", "content": (f"Summary so far:\n{self.summary}\n\n" if self.summary else "")
                 + f"Conversation to add:\n{transcript}"},
            ])
            self.summary = (reply.get("content") or "").strip() or self.summary
        except Exception as exc:  # keep the old summary; the chat itself still works
            logger.warning("Could not summarize older messages: %s", exc)
            return
        metadata.update(summary=self.summary, summary_upto=len(older))
        set_metadata(self.session_id, metadata)

    def system_extra(self) -> str:
        parts = [knowledge.memory_prompt()]
        if self.document_names:
            names = ", ".join(self.document_names)
            parts.append(
                f"## The user's documents\nThe user has uploaded these documents: {names}. Use "
                f"{BUILTIN_APP}__search_documents before answering questions about the user (their name, job, "
                "experience, plans) or anything these documents may cover. Search with a full question or several "
                "keywords and synonyms (a standalone question: name who or what a follow-up's he/it/that means), "
                "and search again with different words if the first results don't answer "
                "the question. Cite the numbered sources you use like [1].")
        if self.mentioned_apps or self.mentioned_documents:
            pointed = [f"the app {s.name} (use its tools)" for s in self.mentioned_apps] + [
                f"the document {d} (search it with {BUILTIN_APP}__search_documents)" for d in self.mentioned_documents]
            parts.append("## The user pointed you at\n" + "; ".join(pointed) + ". Use these for this message.")
        if self.settings.instructions.strip():
            parts.append(f"## Instructions for this conversation\n{self.settings.instructions.strip()}")
        if self.summary:
            parts.append(f"## Summary of earlier messages in this conversation\n{self.summary}")
        return "\n\n".join(p for p in parts if p)

    def agent(self, on_event=None) -> BaseAgent:
        connections = {app_id: state["available"] for app_id, state in self.states.items()}
        agent = BaseAgent(self.registry, connections, on_event=on_event)
        # Question cards only when the agent can act (apps, or creating a workflow): plain chats keep streaming.
        agent.can_ask = any(self.tools_by_name[n].app_id != BUILTIN_APP or n in WORKFLOW_TOOLS for n in self.available)
        return agent


def _cite(result: dict[str, Any], turn) -> dict[str, Any]:
    """Turn [n] markers in the final answer into citations of the sources gathered this turn."""
    if result["status"] in PAUSED or not turn.sources:
        return result
    text, citations = turn.cite(result.get("response") or result.get("message", ""))
    result.update(response=text, message=text, citations=citations)
    return result


def _finish(session_id: Optional[str], user_text: Optional[str], result: dict[str, Any], llm_provider_id: Optional[int],
            usage: Optional[dict[str, Any]] = None) -> AgentRunResponse:
    """Persist the turn to the session (or the pending approval) and build the response."""
    if session_id:
        session = get_session(session_id) or {}
        metadata = dict(session.get("metadata") or {})
        if user_text is not None:
            append_message(session_id, {"role": "user", "content": user_text})
        if result["status"] in PAUSED:
            metadata["pending"] = {"state": result.pop("pending"), "llm_provider_id": llm_provider_id}
            if result.get("pending_question"):
                metadata["pending"]["question"] = result["pending_question"]
        else:
            metadata.pop("pending", None)
            append_message(session_id, {
                "role": "assistant", "content": result.get("response") or result.get("message", ""),
                "events": result["events"], "status": result["status"], "summary": result["summary"], "usage": usage,
                "citations": result.get("citations"),
            })
            tools_used = [e.get("tool_name") for e in result["events"] if e.get("type") == "tool_executed"]
            log_activity("message_received", f"Agent: {(user_text or 'approved action')[:80]}", result.get("summary", ""),
                         {"status": result["status"], "tools": tools_used, "session_id": session_id})
        set_metadata(session_id, metadata)
    result.pop("pending", None)
    return AgentRunResponse(
        status=result["status"], events=result["events"], summary=result["summary"],
        message=result.get("message", ""), response=result.get("response", result.get("message", "")),
        session_id=session_id, pending_action=result.get("pending_action"),
        pending_question=result.get("pending_question"), usage=usage,
        citations=result.get("citations"),
    )


async def _run(prepared: _Prepared, on_event=None) -> dict[str, Any]:
    await prepared.load_history()
    with rag_turn(DEFAULT_WORKSPACE, prepared.session_id) as turn:
        system_extra = prepared.system_extra()
        if prepared.settings.library_id:
            # "Answer from this library": search it for every message and hand the model the sources.
            found = await asyncio.to_thread(retrieve, prepared.task, session_id=prepared.session_id,
                                            collection_ids=[prepared.settings.library_id])
            turn.add(found)
            system_extra += "\n\n## Sources from the attached library\n" + turn.block(found)
        result = await prepared.agent(on_event).run(
            task=prepared.task, context={**prepared.req.context, "system_extra": system_extra},
            available_tools=prepared.available, llm_provider=prepared.llm, history=prepared.history,
        )
        if result["status"] not in PAUSED:
            result = _augment_with_unavailable_apps(result, prepared.task, prepared.unavailable, prepared.tools_by_name, prepared.states)
        return _cite(result, turn)


async def _resume(prepared: _Prepared, state: dict[str, Any], approved: bool, on_event=None) -> dict[str, Any]:
    with rag_turn(DEFAULT_WORKSPACE, prepared.session_id) as turn:
        return _cite(await prepared.agent(on_event).resume(state, approved, prepared.llm), turn)


async def _resume_answers(prepared: _Prepared, state: dict[str, Any], answers: dict[str, Any], on_event=None) -> dict[str, Any]:
    with rag_turn(DEFAULT_WORKSPACE, prepared.session_id) as turn:
        return _cite(await prepared.agent(on_event).resume_with_answers(state, answers, prepared.llm), turn)


def _ensure_session(req: AgentRunRequest) -> Optional[str]:
    # Approvals need somewhere to keep the paused run, so every run belongs to a session.
    return req.session_id or create_session(title=(req.message or req.task)[:80])


def _pending(session_id: str, question: bool = False) -> tuple[dict[str, Any], _Prepared]:
    """The paused run: one waiting for answers (``question``) or for an approval."""
    session = get_session(session_id)
    pending = (session or {}).get("metadata", {}).get("pending")
    if not pending or bool(pending.get("question")) != question:
        waiting = "answers" if question else "approval"
        raise HTTPException(status_code=409, detail=f"Nothing is waiting for {waiting} in this conversation")
    req = AgentRunRequest(message="(continue)", session_id=session_id, llm_provider_id=pending.get("llm_provider_id"))
    prepared = _Prepared(req, session_id)
    if prepared.llm is None:
        raise HTTPException(status_code=400, detail="No LLM provider configured")
    return pending, prepared


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(req: AgentRunRequest) -> AgentRunResponse:
    req.session_id = _ensure_session(req)
    prepared = _Prepared(req, req.session_id)
    with usage_scope() as calls:
        result = await _run(prepared)
    return _finish(req.session_id, prepared.task, result, req.llm_provider_id, usage_total(calls))


@router.post("/sessions/{session_id}/approval", response_model=AgentRunResponse)
async def answer_approval(session_id: str, body: ApprovalRequest) -> AgentRunResponse:
    """Approve or deny the tool call a paused run is waiting on, then continue the run."""
    pending, prepared = _pending(session_id)
    with usage_scope() as calls:
        result = await _resume(prepared, pending["state"], body.approved)
    return _finish(session_id, None, result, prepared.req.llm_provider_id, usage_total(calls))


@router.post("/sessions/{session_id}/answer", response_model=AgentRunResponse)
async def answer_questions(session_id: str, body: AnswerRequest) -> AgentRunResponse:
    """Answer the question cards a paused run is waiting on, then continue the run."""
    pending, prepared = _pending(session_id, question=True)
    with usage_scope() as calls:
        result = await _resume_answers(prepared, pending["state"], body.answers)
    return _finish(session_id, None, result, prepared.req.llm_provider_id, usage_total(calls))


def _stream(session_id: str, user_text: Optional[str], llm_provider_id: Optional[int], work) -> StreamingResponse:
    """Run ``work(on_event)`` as server-sent events: progress events, then ``done`` (or ``error``).

    If the client disconnects (the Stop button), the run is cancelled and what was said so far is
    saved with status ``cancelled``.
    """
    queue: asyncio.Queue = asyncio.Queue()
    partial: list[str] = []

    async def on_event(event: dict[str, Any]) -> None:
        if event.get("type") == "delta":
            partial.append(event.get("text", ""))
        await queue.put(event)

    async def worker() -> None:
        with usage_scope() as calls:
            try:
                result = await work(on_event)
                final = _finish(session_id, user_text, result, llm_provider_id, usage_total(calls))
                await queue.put({"type": "done", **final.model_dump()})
            except asyncio.CancelledError:
                text = "".join(partial).strip()
                _finish(session_id, user_text, {
                    "status": "cancelled", "events": [], "summary": "Stopped by the user",
                    "response": f"{text}\n\n_(stopped)_" if text else "_(stopped before answering)_",
                }, llm_provider_id, usage_total(calls))
                raise
            except Exception as exc:
                logger.warning("Stream error: %s", exc)
                await queue.put({"type": "error", "error": str(exc)})
            finally:
                await queue.put(None)

    async def event_generator() -> AsyncIterator[str]:
        task = asyncio.create_task(worker())
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/run/stream")
async def run_agent_stream(req: AgentRunRequest):
    """Server-sent events: tool_call, tool_result, approval_needed and delta while working, then done."""
    req.session_id = _ensure_session(req)
    prepared = _Prepared(req, req.session_id)
    if prepared.llm is None:
        raise HTTPException(status_code=400, detail="An LLM provider is required")
    return _stream(req.session_id, prepared.task, req.llm_provider_id, lambda on_event: _run(prepared, on_event))


@router.post("/sessions/{session_id}/approval/stream")
async def answer_approval_stream(session_id: str, body: ApprovalRequest):
    """Like /approval, but streams the rest of the reply."""
    pending, prepared = _pending(session_id)
    return _stream(session_id, None, prepared.req.llm_provider_id,
                   lambda on_event: _resume(prepared, pending["state"], body.approved, on_event))


@router.post("/sessions/{session_id}/answer/stream")
async def answer_questions_stream(session_id: str, body: AnswerRequest):
    """Like /answer, but streams the rest of the reply."""
    pending, prepared = _pending(session_id, question=True)
    return _stream(session_id, None, prepared.req.llm_provider_id,
                   lambda on_event: _resume_answers(prepared, pending["state"], body.answers, on_event))


@router.post("/sessions/{session_id}/rewind")
def rewind_session(session_id: str) -> dict[str, Any]:
    """Remove the last user message and everything after it (for Retry and Edit); returns that message."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = session["messages"]
    last_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), None)
    if last_user is None:
        raise HTTPException(status_code=409, detail="There is no message to retry")
    replace_messages(session_id, messages[:last_user])
    metadata = dict(session.get("metadata") or {})
    metadata.pop("pending", None)
    set_metadata(session_id, metadata)
    return {"message": messages[last_user].get("content", "")}


@router.put("/sessions/{session_id}/settings")
def save_chat_settings(session_id: str, settings: ChatSettings) -> dict[str, Any]:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    metadata = dict(session.get("metadata") or {})
    metadata["settings"] = settings.model_dump()
    set_metadata(session_id, metadata)
    return metadata["settings"]


@router.post("/sessions/{session_id}/workflow")
def conversation_to_workflow(session_id: str) -> dict[str, Any]:
    """Turn the tool calls made in a conversation into a workflow you can re-run with one click."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    calls = [
        event for message in session["messages"] if message.get("role") == "assistant"
        for event in message.get("events") or [] if event.get("type") == "tool_executed"
    ]
    if not calls:
        raise HTTPException(status_code=400, detail="This conversation didn't use any tools, so there is nothing to automate")
    request = next((m["content"] for m in session["messages"] if m.get("role") == "user"), "")
    request = request.split("\n\nAttached file '")[0][:500]  # attachment bodies don't belong in the workflow
    nodes: list[dict[str, Any]] = [{"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": {"trigger_type": "manual"}}]
    for index, call in enumerate(calls, start=1):
        nodes.append({"id": f"action_{index}", "type": "action", "name": call["tool_name"].split("__")[-1],
                      "config": {"tool": call["tool_name"], "parameters": call.get("arguments") or {}}})
    references = " ".join(f"{{{{ steps.action_{i}.text }}}}" for i in range(1, len(calls) + 1))
    nodes.append({"id": "llm_1", "type": "llm", "name": "Answer", "config": {
        "prompt": f"Using these results:\n{references}\n\nAnswer this request: {request}"}})
    edges = [{"id": f"edge-{a['id']}-{b['id']}", "source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:])]

    from app.api.routes.workflows import create_workflow
    from app.models.workflow import WorkflowCreate

    created = create_workflow(WorkflowCreate(
        name=(session.get("title") or "Chat workflow")[:60], description=f"Created from a chat: {request[:200]}",
        nodes=nodes, edges=edges, isActive=True,
    ))
    return created.model_dump()

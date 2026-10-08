from __future__ import annotations

import json
import logging
import asyncio
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agent.sessions import (
    append_message,
    create_session,
    delete_session,
    get_history,
    get_session,
    list_sessions,
    set_metadata,
)
from app.agent.abstract import BaseAgent, clean_history
from app.core.database import log_activity
from app.mcp import server_states
from app.llm.utils import get_active_llm_provider, get_default_llm_provider
from app.models.agent import (
    AgentRunRequest,
    AgentRunResponse,
    AgentSessionCreate,
    AgentSession,
    ApprovalRequest,
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
def list_agent_sessions(limit: int = Query(50, ge=1, le=200)) -> list[AgentSession]:
    sessions = list_sessions(limit=limit)
    return [AgentSession(**s) for s in sessions]


@router.get("/sessions/{session_id}")
def get_agent_session(session_id: str) -> AgentSession:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return AgentSession(**session)


@router.delete("/sessions/{session_id}")
def delete_agent_session(session_id: str) -> dict[str, Any]:
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "deleted": True}


# ---------------------------------------------------------------------------
# Agent run (non-streaming)
# ---------------------------------------------------------------------------

MAX_ATTACHMENT_CHARS = 100_000


def _task_with_attachments(req: AgentRunRequest) -> str:
    task = req.task or req.message or ""
    for attachment in req.attachments:
        content = attachment.content
        if len(content) > MAX_ATTACHMENT_CHARS:
            content = content[:MAX_ATTACHMENT_CHARS] + "\n... [file truncated]"
        task += f"\n\nAttached file '{attachment.name}':\n```\n{content}\n```"
    return task


class _Prepared:
    """Everything one agent turn needs, shared by /run, /run/stream and /approval."""

    def __init__(self, req: AgentRunRequest, session_id: Optional[str]):
        self.task = _task_with_attachments(req)
        if not self.task.strip():
            raise HTTPException(status_code=400, detail="task or message is required")
        self.req = req
        self.session_id = session_id
        self.states = server_states()
        self.llm = _resolve_llm_provider(req)
        self.registry = get_tool_registry()
        self.available, self.unavailable, self.tools_by_name, _ = _build_available_tools(req, self.registry, self.states)
        self.history = _session_history(session_id, req)

    def agent(self, on_event=None) -> BaseAgent:
        connections = {app_id: state["available"] for app_id, state in self.states.items()}
        return BaseAgent(self.registry, connections, on_event=on_event)


def _finish(session_id: Optional[str], user_text: Optional[str], result: dict[str, Any], llm_provider_id: Optional[int]) -> AgentRunResponse:
    """Persist the turn to the session (or the pending approval) and build the response."""
    if session_id:
        session = get_session(session_id) or {}
        metadata = dict(session.get("metadata") or {})
        if user_text is not None:
            append_message(session_id, {"role": "user", "content": user_text})
        if result["status"] == "needs_approval":
            metadata["pending"] = {"state": result.pop("pending"), "llm_provider_id": llm_provider_id}
        else:
            metadata.pop("pending", None)
            append_message(session_id, {
                "role": "assistant", "content": result.get("response") or result.get("message", ""),
                "events": result["events"], "status": result["status"], "summary": result["summary"],
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
    )


async def _run(prepared: _Prepared, on_event=None) -> dict[str, Any]:
    result = await prepared.agent(on_event).run(
        task=prepared.task, context=prepared.req.context, available_tools=prepared.available,
        llm_provider=prepared.llm, history=prepared.history,
    )
    if result["status"] != "needs_approval":
        result = _augment_with_unavailable_apps(result, prepared.task, prepared.unavailable, prepared.tools_by_name, prepared.states)
    return result


def _ensure_session(req: AgentRunRequest) -> Optional[str]:
    # Approvals need somewhere to keep the paused run, so every run belongs to a session.
    return req.session_id or create_session(title=(req.message or req.task)[:80])


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(req: AgentRunRequest) -> AgentRunResponse:
    session_id = _ensure_session(req)
    prepared = _Prepared(req, session_id)
    result = await _run(prepared)
    return _finish(session_id, prepared.task, result, req.llm_provider_id)


@router.post("/sessions/{session_id}/approval", response_model=AgentRunResponse)
async def answer_approval(session_id: str, body: ApprovalRequest) -> AgentRunResponse:
    """Approve or deny the tool call a paused run is waiting on, then continue the run."""
    session = get_session(session_id)
    pending = (session or {}).get("metadata", {}).get("pending")
    if not pending:
        raise HTTPException(status_code=409, detail="Nothing is waiting for approval in this conversation")
    req = AgentRunRequest(message="(continue)", session_id=session_id, llm_provider_id=pending.get("llm_provider_id"))
    prepared = _Prepared(req, session_id)
    if prepared.llm is None:
        raise HTTPException(status_code=400, detail="No LLM provider configured")
    agent = prepared.agent()
    schemas = agent._build_tool_schemas(prepared.available)
    result = await agent.resume(pending["state"], body.approved, prepared.llm, schemas)
    return _finish(session_id, None, result, req.llm_provider_id)


@router.post("/run/stream")
async def run_agent_stream(req: AgentRunRequest):
    """Server-sent events: tool_call, tool_result, approval_needed and delta while working, then done."""
    session_id = _ensure_session(req)
    prepared = _Prepared(req, session_id)
    if prepared.llm is None:
        raise HTTPException(status_code=400, detail="An LLM provider is required")
    queue: asyncio.Queue = asyncio.Queue()

    async def worker() -> None:
        try:
            result = await _run(prepared, on_event=queue.put)
            final = _finish(session_id, prepared.task, result, req.llm_provider_id)
            await queue.put({"type": "done", **final.model_dump()})
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

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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

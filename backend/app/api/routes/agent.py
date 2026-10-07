from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agent.sessions import (
    append_message,
    create_session,
    delete_session,
    get_history,
    get_session,
    list_sessions,
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

@router.post("/run", response_model=AgentRunResponse)
async def run_agent(req: AgentRunRequest) -> AgentRunResponse:
    task = req.task or req.message or ""
    if not task:
        raise HTTPException(status_code=400, detail="task or message is required")

    states = server_states()

    llm_provider = _resolve_llm_provider(req)
    tool_registry = get_tool_registry()
    available_tools, unavailable_names, tools_by_name, states = _build_available_tools(
        req, tool_registry, states
    )

    session_id = req.session_id
    history = _session_history(session_id, req)

    agent = BaseAgent(tool_registry, {app_id: state["available"] for app_id, state in states.items()})
    result = await agent.run(
        task=task,
        context=req.context,
        available_tools=available_tools,
        llm_provider=llm_provider,
        history=history,
    )
    result = _augment_with_unavailable_apps(
        result, task, unavailable_names, tools_by_name, states
    )

    if session_id:
        append_message(session_id, {"role": "user", "content": task})
        append_message(session_id, {
            "role": "assistant",
            "content": result.get("response") or result.get("message", ""),
            "events": result["events"],
            "status": result["status"],
            "summary": result["summary"],
        })

    tools_used = [e.get("tool_name") for e in result["events"] if e.get("type") == "tool_executed"]
    log_activity(
        "message_received",
        f"Agent: {task[:80]}",
        result.get("summary", ""),
        {"status": result["status"], "tools": tools_used, "session_id": session_id},
    )

    return AgentRunResponse(
        status=result["status"],
        events=result["events"],
        summary=result["summary"],
        message=result.get("message", ""),
        response=result.get("response", result.get("message", "")),
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Agent run (streaming via SSE)
# ---------------------------------------------------------------------------

@router.post("/run/stream")
async def run_agent_stream(req: AgentRunRequest):
    """Stream the agent's final text response token-by-token as SSE."""
    task = req.task or req.message or ""
    if not task:
        raise HTTPException(status_code=400, detail="task or message is required")

    llm_provider = _resolve_llm_provider(req)
    if llm_provider is None:
        raise HTTPException(status_code=400, detail="An LLM provider is required for streaming")

    session_id = req.session_id
    messages = [*_session_history(session_id, req), {"role": "user", "content": task}]

    async def event_generator() -> AsyncIterator[str]:
        full_content = ""
        try:
            async for chunk in llm_provider.chat_stream(messages=messages):
                full_content += chunk
                yield f"data: {json.dumps({'delta': chunk, 'content': full_content})}\n\n"
        except Exception as exc:
            logger.warning(f"Stream error: {exc}")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        yield "data: [DONE]\n\n"

        if session_id:
            append_message(session_id, {"role": "user", "content": task})
            if full_content:
                append_message(session_id, {"role": "assistant", "content": full_content})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
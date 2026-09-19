from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.database import get_app_states, get_connection
from app.models.agent import AgentRunRequest, AgentRunResponse
from app.tools import build_tool_registry


router = APIRouter(prefix="/api/agent", tags=["agent"])


def _app_label(app_id: str) -> str:
    return app_id.capitalize()


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(req: AgentRunRequest) -> AgentRunResponse:
    conn = get_connection()
    try:
        states = get_app_states(conn)
    finally:
        conn.close()

    llm_provider_id = None
    llm_provider = None
    if req.llm_provider_id:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM llm_providers WHERE id = ? AND enabled = 1",
                (req.llm_provider_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=400, detail="LLM provider not found or disabled")
            llm_provider_id = row["id"]
            from app.llm.registry import LLMRegistry
            registry = LLMRegistry()
            llm_provider = registry.get_provider(llm_provider_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"LLM provider error: {exc}")
        finally:
            conn.close()

    task = req.task or req.message or ""
    tool_registry = build_tool_registry()
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

    from app.agent.provider import DefaultAgentProvider

    agent = DefaultAgentProvider.create_agent(tool_registry, {
        app_id: state["available"] for app_id, state in states.items()
    })
    result = await agent.run(
        task=task,
        context=req.context,
        available_tools=available_tools,
        llm_provider=llm_provider,
    )

    task_lower = task.lower()
    unavailable_apps = {
        tools_by_name[name].app_id
        for name in unavailable_names
        if name in tools_by_name
    }
    for app_id, state in states.items():
        if state["available"]:
            continue
        app = next((item for item in tool_registry.get_available_tools() if item.app_id == app_id), None)
        if app is None:
            continue
        if app_id in task_lower or app.app_id in task_lower:
            unavailable_apps.add(app_id)

    if unavailable_apps:
        messages = []
        for app_id in sorted(unavailable_apps):
            state = states.get(app_id, {})
            reason = "not available" if not state.get("enabled", False) else "not connected"
            messages.append(f"{_app_label(app_id)} is {reason} to Nexus. Connect it to give me access.")
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

    return AgentRunResponse(
        status=result["status"],
        events=result["events"],
        summary=result["summary"],
        message=result.get("message", ""),
        response=result.get("response", result.get("message", "")),
    )

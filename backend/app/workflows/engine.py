from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.database import get_connection
from app.models.workflow import WorkflowRunRequest, WorkflowRunResult
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _ordered_nodes(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not nodes:
        return []
    by_id = {str(node.get("id", index)): node for index, node in enumerate(nodes)}
    order = [str(node.get("id", index)) for index, node in enumerate(nodes)]
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in order}
    indegree = {node_id: 0 for node_id in order}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in outgoing and target in indegree and source != target:
            outgoing[source].append(target)
            indegree[target] += 1
    ready = [node_id for node_id in order if indegree[node_id] == 0]
    result: list[str] = []
    cursor = 0
    while cursor < len(ready):
        node_id = ready[cursor]
        cursor += 1
        result.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(result) != len(order):
        result = order
    return [by_id[node_id] for node_id in result]


def workflow_steps_from_nodes(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, node in enumerate(_ordered_nodes(nodes, edges)):
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        tool = config.get("tool") or node.get("tool")
        app_id = config.get("app") or node.get("app")
        action = config.get("action") or node.get("action")
        if not tool and not (app_id and action):
            continue
        step: dict[str, Any] = {
            "node_id": node.get("id") or f"step-{index + 1}",
            "node_name": node.get("name") or tool or f"{app_id}_{action}",
        }
        if tool:
            step["tool"] = tool
        else:
            step["app"] = app_id
            step["action"] = action
        parameters = config.get("parameters", config.get("params", {}))
        if not isinstance(parameters, dict):
            parameters = {}
        if parameters:
            step["parameters"] = parameters
        steps.append(step)
    return steps


def workflow_steps_from_row(row: Any) -> list[dict[str, Any]]:
    steps = _load_list(row["steps"])
    if steps:
        return steps
    return workflow_steps_from_nodes(_load_list(row["nodes"]), _load_list(row["edges"]))


def _resolve_tool_name(step: dict[str, Any]) -> str:
    if "tool" in step:
        return str(step["tool"])
    if "app" in step and "action" in step:
        return f"{step['app']}_{step['action']}"
    return ""


def _resolve_parameters(
    input_data: dict[str, Any], step: dict[str, Any]
) -> dict[str, Any]:
    parameters = step.get("parameters", step.get("params", {}))
    if not isinstance(parameters, dict):
        parameters = {}
    return {**input_data, **parameters}


def _sanitize(value: Any) -> Any:
    sensitive_fragments = (
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "private_key",
    )
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if not any(fragment in str(key).lower() for fragment in sensitive_fragments)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


async def execute_workflow_step(
    tool: Tool,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    try:
        data = await tool.execute(parameters)
        return {
            "status": "success",
            "data": _sanitize(data),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "data": {},
        }


async def run_workflow(
    workflow_id: int,
    tool_registry: ToolRegistry,
    app_connections: dict[str, bool],
    req: WorkflowRunRequest,
) -> WorkflowRunResult:
    started_at = _utc_now()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise ValueError("Workflow not found")
        steps = workflow_steps_from_row(row)
        enabled = bool(row["enabled"]) and bool(row["is_active"])
    finally:
        conn.close()

    if not enabled:
        event = {
            "id": "workflow-disabled",
            "nodeId": "workflow",
            "nodeName": "Workflow",
            "type": "conditional",
            "timestamp": started_at,
            "step": 0,
            "status": "skipped",
            "error": "Workflow is disabled",
            "connected": False,
        }
        result = WorkflowRunResult(
            id=str(uuid4()),
            workflow_id=workflow_id,
            workflowId=str(workflow_id),
            status="skipped",
            started_at=started_at,
            startedAt=started_at,
            completed_at=_utc_now(),
            completedAt=_utc_now(),
            input_data=req.input_data,
            input=req.input_data,
            output={},
            events=[event],
            trace=[event],
        )
        conn = get_connection()
        try:
            conn.execute("UPDATE workflows SET last_run = ? WHERE id = ?", (_utc_now(), workflow_id))
            conn.commit()
        finally:
            conn.close()
        return result

    events: list[dict[str, Any]] = []
    output_steps: list[dict[str, Any]] = []
    failed = False
    skipped = False
    first_error = ""

    for index, step in enumerate(steps, start=1):
        tool_name = _resolve_tool_name(step)
        node_id = step.get("node_id") or step.get("id") or f"step-{index}"
        node_name = step.get("node_name") or step.get("name") or tool_name
        base_event: dict[str, Any] = {
            "id": f"step-{index}",
            "nodeId": node_id,
            "nodeName": node_name,
            "type": "complete",
            "timestamp": _utc_now(),
            "step": index,
            "tool": tool_name,
            "tool_name": tool_name,
            "status": "success",
        }
        if not tool_name:
            base_event.update({
                "type": "error",
                "status": "failed",
                "error": "Step has no tool or app/action",
            })
            events.append(base_event)
            failed = True
            first_error = first_error or str(base_event["error"])
            continue

        try:
            tool = tool_registry.get_tool(tool_name)
        except Exception:
            base_event.update({
                "type": "error",
                "status": "failed",
                "error": "Tool not found",
            })
            events.append(base_event)
            failed = True
            first_error = first_error or "Tool not found"
            continue

        base_event["app_id"] = tool.app_id
        if not app_connections.get(tool.app_id, False):
            base_event.update({
                "type": "conditional",
                "status": "skipped",
                "connected": False,
                "error": f"App '{tool.app_id}' is not connected",
            })
            events.append(base_event)
            skipped = True
            first_error = first_error or str(base_event["error"])
            continue

        parameters = _resolve_parameters(req.input_data, step)
        outcome = await execute_workflow_step(tool, parameters)
        base_event["status"] = outcome["status"]
        base_event["input"] = _sanitize(parameters)
        base_event["output"] = _sanitize(outcome.get("data", {}))
        base_event["data"] = _sanitize(outcome.get("data", {}))
        if outcome.get("error"):
            base_event["type"] = "error"
            base_event["error"] = str(outcome["error"])
            failed = True
            first_error = first_error or str(outcome["error"])
        events.append(base_event)
        output_steps.append({
            "step": index,
            "tool": tool_name,
            "status": outcome["status"],
            "data": _sanitize(outcome.get("data", {})),
        })

    if failed:
        status = "failed"
    elif skipped:
        status = "partial"
    else:
        status = "completed"

    completed_at = _utc_now()
    result = WorkflowRunResult(
        id=str(uuid4()),
        workflow_id=workflow_id,
        workflowId=str(workflow_id),
        status=status,
        started_at=started_at,
        startedAt=started_at,
        completed_at=completed_at,
        completedAt=completed_at,
        input_data=req.input_data,
        input=req.input_data,
        output={"steps": output_steps},
        error=first_error or None,
        events=events,
        trace=events,
    )
    conn = get_connection()
    try:
        conn.execute("UPDATE workflows SET last_run = ? WHERE id = ?", (completed_at, workflow_id))
        conn.commit()
    finally:
        conn.close()
    return result

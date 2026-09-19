from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.core.database import get_connection, get_effective_app_connections
from app.models.workflow import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowUpdate,
)
from app.tools import build_tool_registry
from app.workflows.engine import run_workflow, workflow_steps_from_row


router = APIRouter(prefix="/api/workflows", tags=["workflows"])


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


def _response_from_row(row: Any) -> WorkflowResponse:
    created_at = row["created_at"] or _utc_now()
    updated_at = row["updated_at"] or created_at
    enabled = bool(row["enabled"])
    is_active = bool(row["is_active"]) if "is_active" in row.keys() else enabled
    return WorkflowResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        steps=_load_list(row["steps"]),
        nodes=_load_list(row["nodes"]),
        edges=_load_list(row["edges"]),
        version=int(row["version"] or 1),
        created_at=created_at,
        updated_at=updated_at,
        created_by=row["created_by"],
        createdAt=created_at,
        updatedAt=updated_at,
        createdBy=row["created_by"],
        enabled=enabled,
        isActive=is_active,
        trigger=row["trigger"] or "manual",
        last_run=row["last_run"],
    )


@router.get("/", response_model=list[WorkflowResponse])
def list_workflows() -> list[WorkflowResponse]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM workflows ORDER BY created_at DESC").fetchall()
        return [_response_from_row(row) for row in rows]
    finally:
        conn.close()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: int) -> WorkflowResponse:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return _response_from_row(row)
    finally:
        conn.close()


@router.post("/", response_model=WorkflowResponse)
def create_workflow(req: WorkflowCreate) -> WorkflowResponse:
    nodes = req.nodes or []
    edges = req.edges or []
    steps = req.steps if req.steps is not None else workflow_steps_from_nodes(nodes, edges)
    is_active = req.isActive if req.isActive is not None else req.enabled
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO workflows
                (name, description, steps, nodes, edges, version, enabled, is_active, trigger, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                req.name,
                req.description,
                json.dumps(steps),
                json.dumps(nodes),
                json.dumps(edges),
                int(is_active),
                int(is_active),
                req.trigger or "manual",
                _utc_now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _response_from_row(row)
    finally:
        conn.close()


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(workflow_id: int, req: WorkflowUpdate) -> WorkflowResponse:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        values = req.model_dump(exclude_unset=True)
        nodes = values.get("nodes", _load_list(row["nodes"]))
        edges = values.get("edges", _load_list(row["edges"]))
        steps = values.get("steps")
        if steps is None and ("nodes" in values or "edges" in values):
            steps = workflow_steps_from_nodes(nodes, edges)
        if steps is None:
            steps = _load_list(row["steps"])

        updates: dict[str, Any] = {}
        for key in ("name", "description", "trigger"):
            if key in values and values[key] is not None:
                updates[key] = values[key]
        updates["steps"] = json.dumps(steps or [])
        updates["nodes"] = json.dumps(nodes or [])
        updates["edges"] = json.dumps(edges or [])
        updates["version"] = int(row["version"] or 1) + 1
        updates["updated_at"] = _utc_now()

        if "isActive" in values:
            is_active = bool(values["isActive"])
            updates["enabled"] = int(is_active)
            updates["is_active"] = int(is_active)
        elif "enabled" in values:
            is_active = bool(values["enabled"])
            updates["enabled"] = int(is_active)
            updates["is_active"] = int(is_active)

        if updates:
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE workflows SET {set_clause} WHERE id = ?",
                list(updates.values()) + [workflow_id],
            )
            conn.commit()
        updated = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        return _response_from_row(updated)
    finally:
        conn.close()


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int) -> Response:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workflow not found")
        conn.commit()
        return Response(status_code=204)
    finally:
        conn.close()


@router.post("/{workflow_id}/run", response_model=WorkflowRunResult)
async def run_workflow_endpoint(workflow_id: int, req: WorkflowRunRequest) -> WorkflowRunResult:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        app_connections = get_effective_app_connections(conn)
    finally:
        conn.close()

    return await run_workflow(workflow_id, build_tool_registry(), app_connections, req)


@router.get("/{workflow_id}/runs")
def get_workflow_runs(workflow_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, name, last_run FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {
            "workflow_id": row["id"],
            "workflowId": str(row["id"]),
            "name": row["name"],
            "last_run": row["last_run"],
            "runs": [],
        }
    finally:
        conn.close()


@router.get("/{workflow_id}/trace")
def get_workflow_trace(workflow_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        steps = workflow_steps_from_row(row)
        app_connections = get_effective_app_connections(conn)
    finally:
        conn.close()

    registry = build_tool_registry()
    trace_steps = []
    for index, step in enumerate(steps):
        try:
            if "tool" in step:
                tool_name = step["tool"]
            elif "app" in step and "action" in step:
                tool_name = f"{step['app']}_{step['action']}"
            else:
                tool_name = "unknown"
            tool = registry.get_tool(tool_name)
            trace_steps.append({
                "id": f"trace-{index + 1}",
                "nodeId": step.get("node_id") or f"step-{index + 1}",
                "nodeName": step.get("node_name") or tool_name,
                "type": "complete" if app_connections.get(tool.app_id, False) else "conditional",
                "timestamp": row["last_run"] or _utc_now(),
                "step": index + 1,
                "tool": tool_name,
                "tool_name": tool_name,
                "app_id": tool.app_id,
                "connected": app_connections.get(tool.app_id, False),
                "parameters": step.get("parameters") or step.get("params") or {},
            })
        except Exception:
            trace_steps.append({
                "id": f"trace-{index + 1}",
                "nodeId": step.get("node_id") or f"step-{index + 1}",
                "nodeName": step.get("node_name") or "unknown",
                "type": "error",
                "timestamp": row["last_run"] or _utc_now(),
                "step": index + 1,
                "tool": step.get("tool") or f"{step.get('app', '')}_{step.get('action', '')}",
                "tool_name": step.get("tool") or f"{step.get('app', '')}_{step.get('action', '')}",
                "error": "Tool not found",
                "connected": False,
            })

    return {
        "workflow_id": workflow_id,
        "workflowId": str(workflow_id),
        "steps": trace_steps,
        "last_run": row["last_run"],
    }

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.database import get_connection, log_activity
from app.mcp import server_availability
from app.models.workflow import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowUpdate,
)
from app.tools import get_tool_registry
from app.triggers.models import TriggerConfig
from app.triggers.registry import list_trigger_types
from app.workflows import inputs, polling, recurrence
from app.workflows.engine import load_workflow_graph, run_workflow, validate_workflow
from app.workflows.scheduler import cron_trigger, next_run_time, parse_trigger, sync_workflow_schedule

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _trigger_info(workflow_id: int, raw: Any) -> dict[str, Any]:
    config = parse_trigger(raw)
    info = config.model_dump()
    if config.type == "webhook" and config.secret:
        info["webhook_path"] = f"/api/webhooks/workflows/{workflow_id}?token={config.secret}"
    if config.type == "app_event":
        info["webhook_path"] = f"/api/webhooks/apps/{config.app_id or '{app_id}'}"
    info["next_run_at"] = next_run_time(workflow_id) if config.type in ("schedule", "recurrence", "poll") else None
    return info


def _response_from_row(row: Any, warnings: Optional[list[str]] = None) -> WorkflowResponse:
    created_at = row["created_at"] or _utc_now()
    updated_at = row["updated_at"] or created_at
    trigger_info = _trigger_info(row["id"], row["trigger"])
    nodes, edges = load_workflow_graph(row)
    return WorkflowResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        steps=_load_json(row["steps"], []),
        nodes=nodes,
        edges=edges,
        version=int(row["version"] or 1),
        created_at=created_at,
        updated_at=updated_at,
        created_by=row["created_by"],
        createdAt=created_at,
        updatedAt=updated_at,
        createdBy=row["created_by"],
        enabled=bool(row["enabled"]),
        isActive=bool(row["is_active"]),
        trigger=trigger_info["type"],
        trigger_config=trigger_info,
        trigger_status=polling.get_status(row["id"]) if trigger_info["type"] == "poll" else None,
        last_status=_last_status(row["id"]),
        llm_provider_id=row["llm_provider_id"],
        last_run=row["last_run"],
        warnings=warnings or [],
    )


def _last_status(workflow_id: int) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT 1", (workflow_id,)
        ).fetchone()
    finally:
        conn.close()
    return row["status"] if row else None


def _trigger_from_nodes(nodes: list[dict[str, Any]], fallback: Any, previous: Optional[TriggerConfig]) -> str:
    """Derive the stored trigger config from the trigger node (or an explicit ``trigger``)."""
    trigger_node = next((n for n in nodes if n.get("type") == "trigger"), None)
    if trigger_node is not None:
        data = dict(trigger_node.get("config") or {})
        data["type"] = data.pop("trigger_type", None) or data.get("type") or "manual"
        if trigger_node.get("app_id") and not data.get("app_id"):
            data["app_id"] = trigger_node["app_id"]
    elif isinstance(fallback, dict):
        data = dict(fallback)
    elif fallback:
        data = parse_trigger(fallback).model_dump()
    else:
        data = {"type": "manual"}

    allowed = set(TriggerConfig.model_fields)
    try:
        config = TriggerConfig(**{k: v for k, v in data.items() if k in allowed})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid trigger configuration: {exc}")
    if config.type not in ("manual", "recurrence", "poll", "schedule", "webhook", "app_event"):
        raise HTTPException(status_code=400, detail=f"Unknown trigger type '{config.type}'")
    if config.type == "schedule":
        try:
            cron_trigger(config)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid schedule: {exc}")
    if config.type == "manual":
        try:
            config.inputs = inputs.validate_definitions(config.inputs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid manual inputs: {exc}")
    if config.type == "recurrence":
        try:
            recurrence.validate(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid recurrence: {exc}")
    if config.type == "poll":
        if not config.tool:
            raise HTTPException(status_code=400, detail="A polling trigger needs a tool to check")
        if not 1 <= config.interval_minutes <= 1440:
            raise HTTPException(status_code=400, detail="Polling interval must be between 1 and 1440 minutes")
    if config.type == "app_event" and not config.app_id:
        raise HTTPException(status_code=400, detail="An app event trigger needs an app")
    if config.type == "webhook":
        # Keep an existing token so saved integrations keep working across edits.
        config.secret = (previous.secret if previous and previous.secret else None) or secrets.token_urlsafe(24)
    else:
        config.secret = None
    return "manual" if config.type == "manual" and not config.inputs else config.model_dump_json()


def _poll_identity(config: TriggerConfig) -> Optional[str]:
    """What a poll's 'seen' state is tied to; None when the trigger is not a poll."""
    if config.type != "poll":
        return None
    return json.dumps([config.tool, config.parameters, config.items_path, config.id_field], sort_keys=True, default=str)


def _validate(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    errors, warnings = validate_workflow(nodes, edges, get_tool_registry())
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return warnings


@router.get("/triggers")
def get_trigger_types() -> list[dict[str, Any]]:
    """Trigger types and the app events each one can fire on (for the editor)."""
    return list_trigger_types()


@router.post("/recurrence/preview")
def preview_recurrence(payload: dict[str, Any]) -> dict[str, Any]:
    """Next three run times for a recurrence config, so the builder can show them."""
    allowed = {"frequency", "interval", "at", "weekdays", "month_day", "timezone"}
    try:
        config = TriggerConfig(type="recurrence", **{k: v for k, v in payload.items() if k in allowed})
        runs = recurrence.next_runs(config)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"next_runs": [run.isoformat() for run in runs]}


@router.post("/validate")
def validate_graph(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    errors, warnings = validate_workflow(nodes, edges, get_tool_registry())
    return {"valid": not errors, "errors": errors, "warnings": warnings}


@router.get("/", response_model=list[WorkflowResponse])
def list_workflows(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[WorkflowResponse]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM workflows ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
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
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Workflow name is required")
    nodes = req.nodes or []
    edges = req.edges or []
    steps = req.steps or []
    warnings = _validate(nodes, edges)
    trigger = _trigger_from_nodes(nodes, req.trigger_config or req.trigger, None)
    is_active = req.isActive if req.isActive is not None else req.enabled
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO workflows
                (name, description, steps, nodes, edges, version, enabled, is_active, trigger, llm_provider_id, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                req.name.strip(), req.description, json.dumps(steps), json.dumps(nodes), json.dumps(edges),
                int(is_active), int(is_active), trigger, req.llm_provider_id, _utc_now(),
            ),
        )
        conn.commit()
        workflow_id = cursor.lastrowid
    finally:
        conn.close()
    sync_workflow_schedule(workflow_id)
    log_activity("workflow_created", f"Workflow '{req.name.strip()}' created", metadata={"workflow_id": workflow_id})
    return _get_with_warnings(workflow_id, warnings)


def _get_with_warnings(workflow_id: int, warnings: list[str]) -> WorkflowResponse:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        return _response_from_row(row, warnings)
    finally:
        conn.close()


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(workflow_id: int, req: WorkflowUpdate) -> WorkflowResponse:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    values = req.model_dump(exclude_unset=True)
    current_nodes, current_edges = load_workflow_graph(row)
    nodes = values.get("nodes", current_nodes) or []
    edges = values.get("edges", current_edges) or []
    warnings = _validate(nodes, edges)

    updates: dict[str, Any] = {}
    if values.get("name") is not None:
        if not values["name"].strip():
            raise HTTPException(status_code=400, detail="Workflow name is required")
        updates["name"] = values["name"].strip()
    if values.get("description") is not None:
        updates["description"] = values["description"]
    if "llm_provider_id" in values:
        updates["llm_provider_id"] = values["llm_provider_id"]
    if "steps" in values:
        updates["steps"] = json.dumps(values["steps"] or [])
    if "nodes" in values or "edges" in values:
        updates["nodes"] = json.dumps(nodes)
        updates["edges"] = json.dumps(edges)
    if "nodes" in values or "trigger" in values or "trigger_config" in values:
        previous = parse_trigger(row["trigger"])
        updates["trigger"] = _trigger_from_nodes(
            nodes, values.get("trigger_config") or values.get("trigger") or row["trigger"], previous
        )
        if _poll_identity(previous) != _poll_identity(parse_trigger(updates["trigger"])):
            polling.reset_state(workflow_id)  # different source: the next check is a fresh baseline
    active = values.get("isActive", values.get("enabled"))
    if active is not None:
        updates["enabled"] = updates["is_active"] = int(bool(active))
    updates["version"] = int(row["version"] or 1) + 1
    updates["updated_at"] = _utc_now()

    conn = get_connection()
    try:
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE workflows SET {set_clause} WHERE id = ?", [*updates.values(), workflow_id])
        conn.commit()
    finally:
        conn.close()
    sync_workflow_schedule(workflow_id)
    return _get_with_warnings(workflow_id, warnings)


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int) -> Response:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Workflow not found")
    sync_workflow_schedule(workflow_id)
    return Response(status_code=204)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResult)
async def run_workflow_endpoint(workflow_id: int, req: WorkflowRunRequest) -> WorkflowRunResult:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, trigger FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    config = parse_trigger(row["trigger"])
    trigger = None
    if config.type == "manual" and config.inputs:
        try:
            values = inputs.coerce(config.inputs, req.input_data or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        trigger = {"type": "manual", "inputs": values}
    elif config.type == "poll" and config.tool:
        # Run button on an app-triggered workflow: test it with the app's latest item.
        try:
            trigger = await polling.latest_item_trigger(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Could not get an item to test with: {exc}")
    return await run_workflow(workflow_id, get_tool_registry(), server_availability(), req, trigger=trigger)


def _run_from_row(row: Any) -> dict[str, Any]:
    input_data = _load_json(row["input_data"], {})
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "workflowId": str(row["workflow_id"]),
        "status": row["status"],
        "started_at": row["started_at"],
        "startedAt": row["started_at"],
        "completed_at": row["completed_at"],
        "completedAt": row["completed_at"],
        "input_data": input_data,
        "input": input_data,
        "output": _load_json(row["output"], {}),
        "error": row["error"],
        "events": _load_json(row["events"], []),
        "trace": _load_json(row["trace"], []),
    }


@router.get("/{workflow_id}/runs")
def get_workflow_runs(workflow_id: int, limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, name, last_run FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        run_rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?",
            (workflow_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return {
        "workflow_id": row["id"],
        "workflowId": str(row["id"]),
        "name": row["name"],
        "last_run": row["last_run"],
        "runs": [_run_from_row(r) for r in run_rows],
    }


@router.get("/{workflow_id}/trace")
def get_workflow_trace(workflow_id: int) -> dict[str, Any]:
    """Trace of the most recent run (empty when the workflow has never run)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, last_run FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        run = conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT 1", (workflow_id,)
        ).fetchone()
    finally:
        conn.close()
    run_data = _run_from_row(run) if run else None
    return {
        "workflow_id": workflow_id,
        "workflowId": str(workflow_id),
        "run_id": run_data["id"] if run_data else None,
        "status": run_data["status"] if run_data else None,
        "steps": run_data["trace"] if run_data else [],
        "last_run": row["last_run"],
    }


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunResult)
def get_workflow_run(workflow_id: int, run_id: str) -> WorkflowRunResult:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ? AND workflow_id = ?", (run_id, workflow_id)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return WorkflowRunResult(**_run_from_row(row))

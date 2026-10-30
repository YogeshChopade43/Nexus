from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.api.routes.settings import user_timezone
from app.auth.owner import owner_id
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
from app.workflows import sharing
from app.workflows import inputs, polling, recurrence
from app.workflows import drafting
from app.workflows.engine import (
    RunState,
    cancel_run,
    load_workflow_graph,
    reusable_outputs,
    run_node,
    run_workflow,
    start_background_run,
    validate_workflow,
)
from app.workflows.templates import TEMPLATES, get_template
from app.workflows.scheduler import cron_trigger, next_run_time, parse_trigger, sync_workflow_schedule

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _own(workflow_id: Any) -> None:
    """404 unless this workflow is the signed-in person's (someone else's looks just like a missing one)."""
    conn = get_connection()
    try:
        mine = conn.execute("SELECT 1 FROM workflows WHERE id = ? AND user_id = ?", (workflow_id, owner_id())).fetchone()
    finally:
        conn.close()
    if mine is None:
        raise HTTPException(status_code=404, detail="Workflow not found")


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
        folder=row["folder"] or "",
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

    if not data.get("timezone"):
        data["timezone"] = user_timezone()
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
        if not config.anchor and config.interval > 1:
            # Fix the cycle's start so "every N days/weeks/months" keeps its rhythm across edits and restarts.
            config.anchor = (previous.anchor if previous and previous.type == "recurrence" and previous.anchor else None) \
                or datetime.now(timezone.utc).date().isoformat()
        try:
            recurrence.validate(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid recurrence: {exc}")
    if not 0 <= config.concurrency <= 20:
        raise HTTPException(status_code=400, detail="Concurrency must be between 0 (unlimited) and 20")
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
    plain_manual = config.type == "manual" and not config.inputs and not config.concurrency
    return "manual" if plain_manual else config.model_dump_json()


def _poll_identity(config: TriggerConfig) -> Optional[str]:
    """What a poll's 'seen' state is tied to; None when the trigger is not a poll."""
    if config.type != "poll":
        return None
    return json.dumps([config.tool, config.parameters, config.items_path, config.id_field, config.poll_mode,
                       config.updated_field], sort_keys=True, default=str)


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
        payload = {**payload, "timezone": payload.get("timezone") or user_timezone()}
        config = TriggerConfig(type="recurrence", **{k: v for k, v in payload.items() if k in allowed})
        runs = recurrence.next_runs(config)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"next_runs": [run.isoformat() for run in runs]}


EXPORT_FORMAT = "nexus-workflow/1"


@router.post("/import", response_model=WorkflowResponse)
def import_workflow(payload: dict[str, Any]) -> WorkflowResponse:
    if payload.get("format") != EXPORT_FORMAT or not isinstance(payload.get("nodes"), list):
        raise HTTPException(status_code=400, detail=f"Not a Nexus workflow export (expected format '{EXPORT_FORMAT}')")
    trigger = dict(payload.get("trigger") or {"type": "manual"})
    trigger.pop("secret", None)  # never trust an imported webhook token; a new one is generated
    nodes, notes = sharing.adopt(payload["nodes"], payload.get("apps") or {}, payload.get("cleared") or [])
    created = create_workflow(WorkflowCreate(
        name=f"{payload.get('name') or 'Workflow'} (imported)", description=payload.get("description") or "",
        nodes=nodes, edges=payload.get("edges") or [], trigger_config=trigger, isActive=False,
    ))
    created.warnings = [*notes, *(w for w in created.warnings if w not in notes)]
    return created


# ---- folders: workflows grouped by a name; one can exist before anything is in it ------------------

class FolderName(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _saved_folders() -> list[str]:
    from app.api.routes.settings import load_user_settings

    return [str(f) for f in load_user_settings().get("workflowFolders") or []]


def _save_folders(folders: list[str]) -> None:
    from app.api.routes.settings import update_user_settings

    update_user_settings({"workflowFolders": sorted(set(folders), key=str.lower)})


def _folder_counts() -> dict[str, int]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT folder, COUNT(*) AS n FROM workflows WHERE folder != '' AND user_id = ? GROUP BY folder",
                            (owner_id(),)).fetchall()
    finally:
        conn.close()
    return {row["folder"]: row["n"] for row in rows}


def _find_folder(name: str) -> Optional[str]:
    """The existing folder called ``name``, whatever its capitals."""
    return next((f for f in {*_saved_folders(), *_folder_counts()} if f.lower() == name.strip().lower()), None)


@router.get("/folders")
def list_folders() -> list[dict[str, Any]]:
    counts = _folder_counts()
    return [{"name": name, "count": counts.get(name, 0)} for name in sorted({*_saved_folders(), *counts}, key=str.lower)]


@router.post("/folders")
def create_folder(body: FolderName) -> list[dict[str, Any]]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Give the folder a name")
    if _find_folder(name):
        raise HTTPException(status_code=409, detail=f"There's already a folder called {_find_folder(name)}")
    _save_folders([*_saved_folders(), name])
    return list_folders()


@router.patch("/folders/{name}")
def rename_folder(name: str, body: FolderName) -> list[dict[str, Any]]:
    old, new = _find_folder(name), body.name.strip()
    if old is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    clash = _find_folder(new)
    if clash and clash != old:
        raise HTTPException(status_code=409, detail=f"There's already a folder called {clash}")
    conn = get_connection()
    try:
        conn.execute("UPDATE workflows SET folder = ? WHERE folder = ? AND user_id = ?", (new, old, owner_id()))
        conn.commit()
    finally:
        conn.close()
    _save_folders([f for f in _saved_folders() if f != old] + [new])
    return list_folders()


@router.delete("/folders/{name}", status_code=204)
def delete_folder(name: str) -> Response:
    """Removes the folder only: its workflows stay, outside any folder."""
    old = _find_folder(name)
    if old is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    conn = get_connection()
    try:
        conn.execute("UPDATE workflows SET folder = '' WHERE folder = ? AND user_id = ?", (old, owner_id()))
        conn.commit()
    finally:
        conn.close()
    _save_folders([f for f in _saved_folders() if f != old])
    return Response(status_code=204)


@router.get("/templates")
def list_templates() -> list[dict[str, Any]]:
    return [{"id": t["id"], "name": t["name"], "description": t["description"], "needs": t.get("needs", [])}
            for t in TEMPLATES]


@router.post("/templates/{template_id}", response_model=WorkflowResponse)
def create_from_template(template_id: str) -> WorkflowResponse:
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    copy = json.loads(json.dumps(template))
    return create_workflow(WorkflowCreate(
        name=copy["name"], description=copy["description"], nodes=copy["nodes"], edges=copy["edges"], isActive=False,
    ))


@router.post("/test-step")
async def test_step(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one step on its own with sample data (the builder's Test step button)."""
    node = payload.get("node")
    if not isinstance(node, dict) or not node.get("type"):
        raise HTTPException(status_code=400, detail="A step to test is required")
    sample = payload.get("sample") or {}
    context = {"input": sample.get("input") or {}, "trigger": sample.get("trigger") or {}, "steps": dict(sample.get("steps") or {}),
               "loop": sample.get("loop"), "error": sample.get("error")}
    provider_id = None
    if payload.get("workflow_id"):
        _own(payload["workflow_id"])
        conn = get_connection()
        try:
            row = conn.execute("SELECT llm_provider_id FROM workflows WHERE id = ?", (payload["workflow_id"],)).fetchone()
        finally:
            conn.close()
        provider_id = row["llm_provider_id"] if row else None
    state = RunState(get_tool_registry(), server_availability(), provider_id)
    started = datetime.now(timezone.utc)
    try:
        result = await run_node(node, context, state)
        outcome = {"status": "success", "output": result["output"], "input": result.get("input", {})}
    except Exception as exc:
        outcome = {"status": "failed", "error": str(exc) or exc.__class__.__name__}
    outcome["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return outcome


@router.post("/draft")
async def draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Draft (but do not save) a workflow from a plain-language description."""
    description = str(payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Describe what the workflow should do")
    try:
        return await drafting.draft_workflow(description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
            "SELECT * FROM workflows WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (owner_id(), limit, offset),
        ).fetchall()
        return [_response_from_row(row) for row in rows]
    finally:
        conn.close()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: int) -> WorkflowResponse:
    _own(workflow_id)
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
                (name, description, steps, nodes, edges, version, enabled, is_active, trigger, llm_provider_id, updated_at, folder,
                 user_id)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.name.strip(), req.description, json.dumps(steps), json.dumps(nodes), json.dumps(edges),
                int(is_active), int(is_active), trigger, req.llm_provider_id, _utc_now(), req.folder.strip(), owner_id(),
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
    _own(workflow_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    values = req.model_dump(exclude_unset=True)
    if "folder" in values:  # filing it away isn't an edit: no new version
        conn = get_connection()
        try:
            conn.execute("UPDATE workflows SET folder = ? WHERE id = ?", ((values.pop("folder") or "").strip(), workflow_id))
            conn.commit()
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        finally:
            conn.close()
        if not values:
            return _get_with_warnings(workflow_id, [])
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
        conn.execute(
            "INSERT INTO workflow_versions (workflow_id, version, snapshot) VALUES (?, ?, ?)",
            (workflow_id, int(row["version"] or 1), json.dumps(_snapshot(row))),
        )
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE workflows SET {set_clause} WHERE id = ?", [*updates.values(), workflow_id])
        conn.commit()
    finally:
        conn.close()
    sync_workflow_schedule(workflow_id)
    return _get_with_warnings(workflow_id, warnings)


def _snapshot(row: Any) -> dict[str, Any]:
    nodes, edges = load_workflow_graph(row)
    trigger = parse_trigger(row["trigger"]).model_dump()
    trigger.pop("secret", None)
    return {"name": row["name"], "description": row["description"] or "", "nodes": nodes, "edges": edges, "trigger": trigger}


@router.get("/{workflow_id}/versions")
def list_versions(workflow_id: int) -> list[dict[str, Any]]:
    _own(workflow_id)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT version, snapshot, created_at FROM workflow_versions WHERE workflow_id = ? ORDER BY version DESC, id DESC",
            (workflow_id,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        snap = json.loads(r["snapshot"])
        result.append({"version": r["version"], "name": snap.get("name"), "saved_at": r["created_at"], "steps": len(snap.get("nodes") or [])})
    return result


@router.post("/{workflow_id}/versions/{version}/restore", response_model=WorkflowResponse)
def restore_version(workflow_id: int, version: int) -> WorkflowResponse:
    _own(workflow_id)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT snapshot FROM workflow_versions WHERE workflow_id = ? AND version = ? ORDER BY id DESC LIMIT 1",
            (workflow_id, version),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    snap = json.loads(row["snapshot"])
    return update_workflow(workflow_id, WorkflowUpdate(
        name=snap["name"], description=snap["description"], nodes=snap["nodes"], edges=snap["edges"], trigger_config=snap["trigger"],
    ))


@router.get("/{workflow_id}/export")
def export_workflow(workflow_id: int) -> dict[str, Any]:
    _own(workflow_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    snapshot = _snapshot(row)
    nodes, apps, cleared = sharing.shareable(snapshot["nodes"])  # safe to send: no keys, no local ids
    return {"format": EXPORT_FORMAT, **snapshot, "nodes": nodes, "apps": apps, "cleared": cleared}


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int) -> Response:
    _own(workflow_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT name FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        conn.commit()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    sync_workflow_schedule(workflow_id)
    log_activity("workflow_deleted", f"Workflow '{row['name']}' deleted", metadata={"workflow_id": workflow_id})
    return Response(status_code=204)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResult)
async def run_workflow_endpoint(
    workflow_id: int, req: WorkflowRunRequest, background: bool = Query(False),
) -> WorkflowRunResult:
    """Run now. With ``background=true`` the run starts and its id returns at once; poll it for progress."""
    _own(workflow_id)
    from app.api.routes import run_once

    run_once.refuse_manual_run(workflow_id, req.confirm)
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
    if background:
        run_id = start_background_run(workflow_id, get_tool_registry(), server_availability(), req, trigger=trigger)
        return WorkflowRunResult(id=run_id, workflow_id=workflow_id, workflowId=str(workflow_id), status="running")
    return await run_workflow(workflow_id, get_tool_registry(), server_availability(), req, trigger=trigger)


@router.post("/{workflow_id}/runs/{run_id}/cancel")
def cancel_workflow_run(workflow_id: int, run_id: str) -> dict[str, Any]:
    _own(workflow_id)
    if not cancel_run(run_id):
        raise HTTPException(status_code=409, detail="This run is not running")
    return {"run_id": run_id, "cancelled": True}


@router.post("/{workflow_id}/runs/{run_id}/rerun", response_model=WorkflowRunResult)
async def rerun_from_failure(workflow_id: int, run_id: str) -> WorkflowRunResult:
    """Run again, reusing the outputs of steps that succeeded last time so they are not repeated."""
    _own(workflow_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflow_runs WHERE id = ? AND workflow_id = ?", (run_id, workflow_id)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    previous = _run_from_row(row)
    input_data = dict(previous["input_data"])
    trigger = input_data.pop("trigger", None)
    practice = input_data.pop("practice", False) is True  # a practice run's re-run is a practice run too
    new_id = start_background_run(
        workflow_id, get_tool_registry(), server_availability(), WorkflowRunRequest(input_data=input_data, practice=practice),
        trigger=trigger, reuse=reusable_outputs(previous["events"]),
    )
    return WorkflowRunResult(id=new_id, workflow_id=workflow_id, workflowId=str(workflow_id), status="running")


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
    _own(workflow_id)
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
    _own(workflow_id)
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
    _own(workflow_id)
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

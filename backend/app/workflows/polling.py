"""Polling triggers: call an MCP tool on an interval and start one run per new item.

The first successful check only records what already exists (a baseline), so turning a
trigger on never floods the user with runs for old items. This mirrors Power Automate.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.database import get_connection
from app.core.exceptions import AppNotConnectedError, ToolNotFoundError
from app.mcp import server_availability
from app.models.workflow import WorkflowRunRequest
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)

MAX_SEEN = 1000
MAX_RUNS_PER_CHECK = 25
ID_FIELDS = ("id", "number", "key", "uid", "url")
UPDATED_FIELDS = ("last_edited_time", "updated_at", "updatedAt", "updated", "modified_at", "modified", "last_modified")
CREATED_FIELDS = ("created_time", "created_at", "createdAt", "created")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_items(result: dict[str, Any], items_path: str) -> list:
    data = result.get("data")
    if items_path:
        value: Any = data
        for part in items_path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, list):
            return value
    elif isinstance(data, list):
        return data
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    raise ValueError("Could not find a list of items in the result; set the items path")


def detect_id_field(items: list, id_field: str) -> str:
    if id_field or not items or not isinstance(items[0], dict):
        return id_field
    return next((field for field in ID_FIELDS if field in items[0]), "")


def detect_field(items: list, explicit: str, candidates: tuple[str, ...]) -> str:
    if explicit or not items or not isinstance(items[0], dict):
        return explicit
    return next((name for name in candidates if name in items[0]), "")


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def identity(item: Any, id_field: str) -> str:
    if id_field and isinstance(item, dict) and item.get(id_field) is not None:
        return str(item[id_field])
    return hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()


# ---- state ------------------------------------------------------------------

def _load_state(workflow_id: int) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM trigger_state WHERE workflow_id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "seen": json.loads(row["seen"] or "[]"),
        "baseline_done": bool(row["baseline_done"]),
        "last_checked_at": row["last_checked_at"],
        "last_error": row["last_error"],
        "baseline_at": row["baseline_at"],
    }


def _save_state(
    workflow_id: int, seen: list[str], baseline_done: bool, error: Optional[str], baseline_at: Optional[str] = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO trigger_state (workflow_id, seen, baseline_done, last_checked_at, last_error, baseline_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET seen = excluded.seen, baseline_done = excluded.baseline_done,
                last_checked_at = excluded.last_checked_at, last_error = excluded.last_error,
                baseline_at = COALESCE(excluded.baseline_at, trigger_state.baseline_at)
            """,
            (workflow_id, json.dumps(seen[-MAX_SEEN:]), int(baseline_done), _now(), error, baseline_at),
        )
        conn.commit()
    finally:
        conn.close()


def reset_state(workflow_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM trigger_state WHERE workflow_id = ?", (workflow_id,))
        conn.commit()
    finally:
        conn.close()


def get_status(workflow_id: int) -> Optional[dict[str, Any]]:
    state = _load_state(workflow_id)
    if state is None:
        return None
    return {"last_checked_at": state["last_checked_at"], "last_error": state["last_error"]}


# ---- check --------------------------------------------------------------------

async def fetch_items(config: Any) -> list:
    """Call the trigger's tool and return its items. Raises ValueError with a user-facing message."""
    from app.auth.owner import owns_app

    try:
        tool = get_tool_registry().get_tool(config.tool)
        if not owns_app(tool.app_id):  # someone else's app: as if it weren't connected
            raise AppNotConnectedError(tool.app_id)
        result = await tool.execute(dict(config.parameters))
    except (ToolNotFoundError, AppNotConnectedError):
        raise ValueError(f"{config.tool.split('__')[0]} is not connected")
    except Exception as exc:
        raise ValueError(str(exc) or exc.__class__.__name__)
    return find_items(result, config.items_path)


async def latest_item_trigger(config: Any) -> dict[str, Any]:
    """Trigger data for a manual Run of a polling workflow: the app's first (most recent) item."""
    items = await fetch_items(config)
    if not items:
        raise ValueError("The app returned no items to test with")
    return {"type": "poll", "item": items[0], "tool": config.tool, "test": True}


async def poll_once(workflow_id: int) -> dict[str, Any]:
    """One check for new items, as the workflow's owner (the scheduler has no one signed in)."""
    from app.auth.owner import as_user

    conn = get_connection()
    try:
        row = conn.execute("SELECT user_id FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["user_id"] is None:
        return await _poll_once(workflow_id)
    with as_user(int(row["user_id"])):
        return await _poll_once(workflow_id)


async def _poll_once(workflow_id: int) -> dict[str, Any]:
    from app.workflows.engine import run_workflow
    from app.workflows.scheduler import parse_trigger

    conn = get_connection()
    try:
        row = conn.execute("SELECT trigger FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"started": 0, "error": "Workflow not found"}
    config = parse_trigger(row["trigger"])
    if config.type != "poll" or not config.tool:
        return {"started": 0, "error": "Workflow does not have a polling trigger"}

    state = _load_state(workflow_id) or {"seen": [], "baseline_done": False}
    try:
        items = await fetch_items(config)
    except ValueError as exc:
        _save_state(workflow_id, state["seen"], state["baseline_done"], str(exc))
        return {"started": 0, "error": str(exc)}

    from app.workflows.engine import evaluate_condition

    id_field = detect_id_field(items, config.id_field)
    track_updates = config.poll_mode == "new_or_updated"
    updated_field = detect_field(items, config.updated_field, UPDATED_FIELDS) if track_updates else ""
    created_field = "" if track_updates else detect_field(items, config.created_field, CREATED_FIELDS)
    baseline_at = _parse_time(state.get("baseline_at"))
    seen = list(state["seen"])
    known = set(seen)
    new_items = []
    for item in items:
        key = identity(item, id_field)
        if updated_field and isinstance(item, dict) and item.get(updated_field) is not None:
            key = f"{key}@{item[updated_field]}"  # each edit is a new identity in "new or updated" mode
        if key in known:
            continue
        known.add(key)
        seen.append(key)
        created = _parse_time(item.get(created_field)) if created_field and isinstance(item, dict) else None
        if baseline_at and created and created < baseline_at:
            continue  # existed before the trigger started; it only showed up now because it was edited
        if config.filter_field and not evaluate_condition(
            {"field": config.filter_field, "operator": config.filter_operator or "truthy", "value": config.filter_value},
            {"item": item},
        ):
            continue
        new_items.append(item)

    if not state["baseline_done"]:
        _save_state(workflow_id, seen, True, None, baseline_at=_now())
        return {"started": 0, "error": None}

    warning = None
    if len(new_items) > MAX_RUNS_PER_CHECK:
        warning = f"{len(new_items)} new items found; started only the first {MAX_RUNS_PER_CHECK}"
        logger.warning("Workflow %s: %s", workflow_id, warning)
    # Record before running so a crash mid-check can't re-run the same items forever.
    _save_state(workflow_id, seen, True, warning)

    started = 0
    for item in new_items[:MAX_RUNS_PER_CHECK]:
        trigger = {"type": "poll", "item": item, "tool": config.tool}
        try:
            await run_workflow(workflow_id, get_tool_registry(), server_availability(), WorkflowRunRequest(), trigger=trigger)
            started += 1
        except Exception:
            logger.exception("Polling run of workflow %s failed to start", workflow_id)
    return {"started": started, "error": None}

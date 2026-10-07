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
    }


def _save_state(workflow_id: int, seen: list[str], baseline_done: bool, error: Optional[str]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO trigger_state (workflow_id, seen, baseline_done, last_checked_at, last_error)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET seen = excluded.seen, baseline_done = excluded.baseline_done,
                last_checked_at = excluded.last_checked_at, last_error = excluded.last_error
            """,
            (workflow_id, json.dumps(seen[-MAX_SEEN:]), int(baseline_done), _now(), error),
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
    try:
        tool = get_tool_registry().get_tool(config.tool)
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

    id_field = detect_id_field(items, config.id_field)
    seen = list(state["seen"])
    known = set(seen)
    new_items = []
    for item in items:
        key = identity(item, id_field)
        if key not in known:
            known.add(key)
            seen.append(key)
            new_items.append(item)

    if not state["baseline_done"]:
        _save_state(workflow_id, seen, True, None)
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

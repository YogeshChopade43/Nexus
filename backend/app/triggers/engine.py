from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.database import get_connection
from app.triggers.models import TriggerConfig, TriggerEvent, TriggerMatch
from app.workflows.engine import run_workflow
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        import json
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if parsed is not None else default


def _parse_trigger_config(value: Any) -> Optional[TriggerConfig]:
    """Parse a trigger config from a JSON string or dict."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            import json
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None
    try:
        return TriggerConfig(**value)
    except Exception:
        return None


def _event_matches_trigger(event: TriggerEvent, trigger: TriggerConfig) -> bool:
    """Check if an event matches a trigger configuration."""
    if not trigger.enabled:
        return False

    # An empty trigger event means "any event from this app".
    if trigger.event and event.event_name != trigger.event:
        return False
    if trigger.app_id and event.app_id != trigger.app_id:
        return False

    # Apply filters
    for key, expected in trigger.filters.items():
        actual = event.payload.get(key)
        if isinstance(expected, dict):
            # Complex filter: {field: {op: value}}
            for field, cond in expected.items():
                field_val = event.payload.get(field)
                if isinstance(cond, dict):
                    for op, op_val in cond.items():
                        if not _apply_filter_op(field_val, op, op_val):
                            return False
                elif field_val != cond:
                    return False
        elif actual != expected:
            return False

    return True


def _apply_filter_op(value: Any, op: str, expected: Any) -> bool:
    """Apply a single filter operator."""
    if op == "eq":
        return value == expected
    if op == "ne":
        return value != expected
    if op == "in":
        return value in expected if isinstance(expected, (list, tuple, set)) else False
    if op == "contains":
        try:
            return expected in value
        except TypeError:
            return False
    if op == "starts_with":
        return str(value).startswith(str(expected)) if value else False
    if op == "ends_with":
        return str(value).endswith(str(expected)) if value else False
    if op == "regex":
        import re
        try:
            return bool(re.search(str(expected), str(value)))
        except re.error:
            return False
    return value == expected


def matching_workflows(event: TriggerEvent) -> list[TriggerMatch]:
    """Every active workflow whose app-event trigger matches the event."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, trigger FROM workflows
            WHERE enabled = 1 AND is_active = 1 AND trigger IS NOT NULL AND trigger != 'manual'
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    matches = []
    for row in rows:
        config = _parse_trigger_config(row["trigger"])
        if config is None or config.type != "app_event" or not _event_matches_trigger(event, config):
            continue
        matches.append(TriggerMatch(
            matched=True,
            workflow_id=row["id"],
            trigger_config=config,
            reason=f"Matched event '{event.event_name}'",
            input_data={
                "type": "app_event",
                "app_id": event.app_id,
                "event": event.event_name,
                "payload": event.payload,
                "timestamp": event.timestamp,
            },
        ))
    return matches


def match_trigger(event: TriggerEvent) -> TriggerMatch:
    matches = matching_workflows(event)
    return matches[0] if matches else TriggerMatch(
        matched=False, reason=f"No workflow trigger matched event '{event.event_name}'"
    )


async def execute_triggered_workflow(match: TriggerMatch) -> dict[str, Any]:
    """Execute a workflow that was triggered by an event."""
    if not match.matched or match.workflow_id is None:
        return {"status": "skipped", "reason": match.reason}

    from app.mcp import server_availability
    from app.models.workflow import WorkflowRunRequest

    app_connections = server_availability()

    result = await run_workflow(
        match.workflow_id, get_tool_registry(), app_connections, WorkflowRunRequest(), trigger=match.input_data
    )
    return {"status": result.status, "workflow_id": match.workflow_id, "run_id": result.id, "error": result.error}


class TriggerEngine:
    """Matches incoming events to workflows and runs every match."""

    async def handle_event(self, event: TriggerEvent) -> list[dict[str, Any]]:
        results = []
        for match in matching_workflows(event):
            logger.info("Trigger matched: workflow_id=%s event=%s", match.workflow_id, event.event_name)
            try:
                results.append(await execute_triggered_workflow(match))
            except Exception as exc:
                logger.exception("Triggered workflow %s failed", match.workflow_id)
                results.append({"status": "failed", "workflow_id": match.workflow_id, "error": str(exc)})
        return results

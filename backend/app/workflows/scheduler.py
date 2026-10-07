"""Cron scheduling for workflows whose trigger type is ``schedule``."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import get_connection
from app.mcp import server_availability
from app.models.workflow import WorkflowRunRequest
from app.triggers.models import TriggerConfig
from app.workflows import recurrence
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def parse_trigger(raw: Any) -> TriggerConfig:
    """Workflow ``trigger`` column -> TriggerConfig. Legacy plain strings mean that type."""
    if isinstance(raw, dict):
        return TriggerConfig(**raw)
    if not raw or raw == "manual":
        return TriggerConfig(type="manual")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return TriggerConfig(type=str(raw))
    return TriggerConfig(**data) if isinstance(data, dict) else TriggerConfig(type="manual")


def cron_trigger(config: TriggerConfig) -> CronTrigger:
    """Raises ValueError for an invalid cron expression or timezone."""
    if not config.schedule:
        raise ValueError("A schedule trigger needs a cron expression, e.g. '0 9 * * 1-5'")
    return CronTrigger.from_crontab(config.schedule, timezone=config.timezone or "UTC")


async def _run_scheduled(workflow_id: int, trigger_type: str = "schedule") -> None:
    from app.workflows.engine import run_workflow

    app_connections = server_availability()
    trigger = {"type": trigger_type, "fired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    try:
        await run_workflow(workflow_id, get_tool_registry(), app_connections, WorkflowRunRequest(), trigger=trigger)
    except Exception:
        logger.exception("Scheduled run of workflow %s failed", workflow_id)


def sync_workflow_schedule(workflow_id: int) -> Optional[str]:
    """Add, replace or remove the job for one workflow. Returns the next run time, if any."""
    if _scheduler is None:
        return None
    job_id = f"workflow-{workflow_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT trigger, enabled, is_active FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or not (row["enabled"] and row["is_active"]):
        return None
    try:
        config = parse_trigger(row["trigger"])
        if not config.enabled:
            return None
        if config.type == "schedule":
            job_trigger = cron_trigger(config)
        elif config.type == "recurrence":
            job_trigger = recurrence.build_trigger(config)
        elif config.type == "poll":
            from app.workflows.polling import poll_once

            job = _scheduler.add_job(
                poll_once,
                IntervalTrigger(minutes=config.interval_minutes),
                args=[workflow_id],
                id=job_id,
                max_instances=1,
                coalesce=True,
            )
            return job.next_run_time.isoformat() if job.next_run_time else None
        else:
            return None
        job = _scheduler.add_job(
            _run_scheduled,
            job_trigger,
            args=[workflow_id, config.type],
            id=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
    except Exception as exc:
        logger.warning("Could not schedule workflow %s: %s", workflow_id, exc)
        return None
    return job.next_run_time.isoformat() if job.next_run_time else None


def next_run_time(workflow_id: int) -> Optional[str]:
    job = _scheduler.get_job(f"workflow-{workflow_id}") if _scheduler else None
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    conn = get_connection()
    try:
        ids = [row["id"] for row in conn.execute("SELECT id FROM workflows").fetchall()]
    finally:
        conn.close()
    for workflow_id in ids:
        sync_workflow_schedule(workflow_id)
    logger.info("Workflow scheduler started with %d job(s)", len(_scheduler.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

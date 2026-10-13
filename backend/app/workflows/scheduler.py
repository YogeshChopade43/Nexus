"""Cron scheduling for workflows whose trigger type is ``schedule``."""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import get_connection, purge_old_records
from app.mcp import server_availability
from app.models.workflow import WorkflowRunRequest
from app.triggers.models import TriggerConfig
from app.workflows import recurrence
from app.tools import get_tool_registry

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None

# A run that was due while the computer slept still fires on wake, up to this late.
MISFIRE_GRACE = 6 * 3600
# On startup, the latest run missed while Nexus was off (within this window) runs once.
CATCH_UP_WINDOW = timedelta(hours=12)
# Set while a caught-up run executes, so its reminders can say when they were due.
due_at: ContextVar[Optional[datetime]] = ContextVar("workflow_due_at", default=None)


def due_note() -> str:
    """Inside a caught-up run: " (was due at 1:00 PM)" in the user's timezone. Otherwise nothing."""
    due = due_at.get()
    if due is None:
        return ""
    from zoneinfo import ZoneInfo

    from app.api.routes.settings import user_timezone

    local = due.astimezone(ZoneInfo(user_timezone() or "UTC"))
    return f" (was due at {local.strftime('%I:%M %p').lstrip('0')})"


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
    fields = config.schedule.split()
    if len(fields) == 5:
        fields[4] = _cron_weekdays(fields[4])
    return CronTrigger.from_crontab(" ".join(fields), timezone=config.timezone or "UTC")


_DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _cron_weekdays(field: str) -> str:
    """Standard cron weekdays (0 or 7 = Sunday) as day names: APScheduler reads numbers with 0 = Monday,
    so "1-5" would otherwise run Tuesday to Saturday."""
    if field == "*" or any(c.isalpha() for c in field):
        return field
    days: list[str] = []
    for part in field.split(","):
        span, _, step = part.partition("/")
        if span == "*":
            first, last = 0, 6
        elif "-" in span:
            first, last = (int(x) for x in span.split("-", 1))
        else:
            first = last = int(span)
        for number in range(first, last + 1, int(step or 1)):
            name = _DAY_NAMES[number % 8 if number <= 7 else number % 7]
            if name not in days:
                days.append(name)
    return ",".join(days)


async def _run_scheduled(workflow_id: int, trigger_type: str = "schedule", scheduled_for: Optional[str] = None) -> None:
    from app.workflows.engine import run_workflow

    app_connections = server_availability()
    trigger = {"type": trigger_type, "fired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if scheduled_for:
        trigger.update(missed=True, scheduled_for=scheduled_for)
    token = due_at.set(datetime.fromisoformat(scheduled_for) if scheduled_for else None)
    try:
        await run_workflow(workflow_id, get_tool_registry(), app_connections, WorkflowRunRequest(), trigger=trigger)
    except Exception:
        logger.exception("Scheduled run of workflow %s failed", workflow_id)
    finally:
        due_at.reset(token)


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def missed_run(config: TriggerConfig, last_run: Optional[str], since: datetime, now: datetime) -> Optional[datetime]:
    """The latest time the trigger was due between ``since`` and ``now`` that no run covered (None if none).
    Every-few-minutes workflows aren't caught up: their next run comes soon anyway."""
    if config.type == "recurrence" and config.frequency != "minute":
        trigger = recurrence.build_trigger(config, now=since)
    elif config.type == "schedule":
        trigger = cron_trigger(config)
    else:
        return None
    latest, previous, cursor = None, None, since
    for _ in range(10_000):  # bounded: a cron firing every minute stops here
        fire = trigger.get_next_fire_time(previous, cursor)
        if fire is None or fire > now:
            break
        latest, previous, cursor = fire, fire, fire + timedelta(seconds=1)
    ran = _parse_time(last_run)
    return None if latest is None or (ran and ran >= latest) else latest


async def catch_up_missed_runs() -> list[int]:
    """Run, once each, the scheduled workflows that were due while Nexus was off. Returns their ids."""
    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, trigger, last_run, created_at, updated_at FROM workflows "
                            "WHERE enabled = 1 AND is_active = 1").fetchall()
    finally:
        conn.close()
    ran = []
    for row in rows:
        try:
            config = parse_trigger(row["trigger"])
            # Never before the workflow existed or last changed: that time wasn't on its schedule.
            changed = [t for t in (_parse_time(row["created_at"]), _parse_time(row["updated_at"])) if t]
            since = max([now - CATCH_UP_WINDOW, *changed])
            due = missed_run(config, row["last_run"], since, now) if config.enabled else None
        except Exception as exc:
            logger.warning("Couldn't check workflow %s for missed runs: %s", row["id"], exc)
            continue
        if due is not None:
            logger.info("Workflow %s was due at %s while Nexus was off: running it now", row["id"], due.isoformat())
            await _run_scheduled(row["id"], config.type, due.isoformat())
            ran.append(row["id"])
    return ran


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
            misfire_grace_time=MISFIRE_GRACE,
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
    # Shortly after startup: runs that were due while Nexus was off.
    _scheduler.add_job(catch_up_missed_runs, id="catch-up", replace_existing=True,
                       next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20))
    # Daily cleanup of old runs and activity, also once shortly after startup.
    _scheduler.add_job(_cleanup, IntervalTrigger(hours=24), id="cleanup", replace_existing=True,
                       next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1))
    from app.mcp import registry

    if registry.auto_sync_enabled():  # Marketplace: refresh the MCP Registry copy daily
        _scheduler.add_job(registry.sync, IntervalTrigger(hours=24), id="registry-sync", replace_existing=True)
    logger.info("Workflow scheduler started with %d job(s)", len(_scheduler.get_jobs()))


def _cleanup() -> None:
    from app.api.routes.settings import load_user_settings

    try:
        days = int(load_user_settings().get("retentionDays") or 0)
        purge_old_records(days)
        from app.files import purge_older_than  # files the agent made, on the same schedule

        purge_older_than(days)
    except Exception:
        logger.exception("Cleanup of old runs failed")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

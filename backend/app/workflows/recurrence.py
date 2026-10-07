"""Power Automate–style recurrence ("every weekday at 09:00") → APScheduler triggers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.triggers.models import TriggerConfig

FREQUENCIES = ("minute", "hour", "day", "week", "month")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"timezone '{name}' is not a valid IANA timezone (e.g. 'Asia/Kolkata')")


def validate(config: TriggerConfig) -> None:
    if config.frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {', '.join(FREQUENCIES)}")
    if not 1 <= config.interval <= 1000:
        raise ValueError("interval must be between 1 and 1000")
    if config.frequency == "minute" and config.interval < 5:
        raise ValueError("interval must be at least 5 when repeating every N minutes")
    if config.frequency in ("week", "month") and config.interval != 1:
        raise ValueError(f"interval greater than 1 is not supported for every {config.frequency}")
    if not _AT.match(config.at or ""):
        raise ValueError("at must be a time of day as HH:MM (00:00–23:59)")
    if config.frequency == "week":
        if not config.weekdays:
            raise ValueError("weekdays must include at least one day")
        unknown = set(config.weekdays) - set(WEEKDAYS)
        if unknown:
            raise ValueError(f"weekdays has unknown day(s): {', '.join(sorted(unknown))}")
    if config.frequency == "month" and not (config.month_day and 1 <= config.month_day <= 31):
        raise ValueError("month_day must be between 1 and 31")
    _zone(config.timezone)


def build_trigger(config: TriggerConfig, now: Optional[datetime] = None) -> BaseTrigger:
    validate(config)
    tz = _zone(config.timezone)
    hour, minute = (int(part) for part in config.at.split(":"))
    if config.frequency == "minute":
        return IntervalTrigger(minutes=config.interval, timezone=tz)
    if config.frequency == "hour":
        return IntervalTrigger(hours=config.interval, timezone=tz)
    if config.frequency == "day":
        if config.interval == 1:
            return CronTrigger(hour=hour, minute=minute, timezone=tz)
        # ponytail: the N-day cycle restarts from now on each save/restart; persist an anchor date if exact phase matters.
        current = (now or datetime.now(tz)).astimezone(tz)
        start = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= current:
            start += timedelta(days=1)
        return IntervalTrigger(days=config.interval, start_date=start, timezone=tz)
    if config.frequency == "week":
        days = ",".join(day for day in WEEKDAYS if day in config.weekdays)
        return CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=tz)
    return CronTrigger(day=config.month_day, hour=hour, minute=minute, timezone=tz)


def next_runs(config: TriggerConfig, count: int = 3, now: Optional[datetime] = None) -> list[datetime]:
    now = now or datetime.now(_zone(config.timezone))
    trigger = build_trigger(config, now=now)
    runs: list[datetime] = []
    previous = None
    cursor = now
    while len(runs) < count:
        fire = trigger.get_next_fire_time(previous, cursor)
        if fire is None:
            break
        runs.append(fire)
        previous, cursor = fire, fire + timedelta(seconds=1)
    return runs

"""Power Automate–style recurrence ("every weekday at 09:00") → APScheduler triggers."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
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
    if not _AT.match(config.at or ""):
        raise ValueError("at must be a time of day as HH:MM (00:00–23:59)")
    if config.frequency == "week":
        if not config.weekdays:
            raise ValueError("weekdays must include at least one day")
        unknown = set(config.weekdays) - set(WEEKDAYS)
        if unknown:
            raise ValueError(f"weekdays has unknown day(s): {', '.join(sorted(unknown))}")
    if config.frequency == "month" and not (config.month_day == -1 or (config.month_day and 1 <= config.month_day <= 31)):
        raise ValueError("month_day must be between 1 and 31, or -1 for the last day of the month")
    _zone(config.timezone)
    if config.anchor:
        try:
            date.fromisoformat(config.anchor)
        except ValueError:
            raise ValueError("anchor must be a date as YYYY-MM-DD")


class _EveryNth(BaseTrigger):
    """Wraps a weekly/monthly cron trigger and keeps only every Nth week or month after the anchor."""

    def __init__(self, inner: BaseTrigger, unit: str, every: int, anchor: date) -> None:
        self.inner, self.unit, self.every, self.anchor = inner, unit, every, anchor

    def _accept(self, fire: datetime) -> bool:
        if self.unit == "week":
            weeks = ((fire.date() - fire.date().weekday() * timedelta(days=1)) - (self.anchor - self.anchor.weekday() * timedelta(days=1))).days // 7
            return weeks % self.every == 0
        months = (fire.year * 12 + fire.month) - (self.anchor.year * 12 + self.anchor.month)
        return months % self.every == 0

    def get_next_fire_time(self, previous_fire_time, now):
        fire = self.inner.get_next_fire_time(previous_fire_time, now)
        for _ in range(5000):  # bounded: at most every 1000 months is searched
            if fire is None or self._accept(fire):
                return fire
            fire = self.inner.get_next_fire_time(fire, fire + timedelta(seconds=1))
        return None

    def __str__(self) -> str:
        return f"every {self.every} {self.unit}s ({self.inner})"


def build_trigger(config: TriggerConfig, now: Optional[datetime] = None) -> BaseTrigger:
    validate(config)
    tz = _zone(config.timezone)
    hour, minute = (int(part) for part in config.at.split(":"))
    if config.frequency == "minute":
        return IntervalTrigger(minutes=config.interval, timezone=tz)
    if config.frequency == "hour":
        return IntervalTrigger(hours=config.interval, timezone=tz)
    anchor = date.fromisoformat(config.anchor) if config.anchor else (now or datetime.now(tz)).astimezone(tz).date()
    if config.frequency == "day":
        if config.interval == 1:
            return CronTrigger(hour=hour, minute=minute, timezone=tz)
        # Counting from the stored anchor keeps the same days across restarts and edits.
        start = datetime(anchor.year, anchor.month, anchor.day, hour, minute, tzinfo=tz)
        return IntervalTrigger(days=config.interval, start_date=start, timezone=tz)
    if config.frequency == "week":
        days = ",".join(day for day in WEEKDAYS if day in config.weekdays)
        weekly = CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=tz)
        return weekly if config.interval == 1 else _EveryNth(weekly, "week", config.interval, anchor)
    day = "last" if config.month_day == -1 else config.month_day
    monthly = CronTrigger(day=day, hour=hour, minute=minute, timezone=tz)
    return monthly if config.interval == 1 else _EveryNth(monthly, "month", config.interval, anchor)


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

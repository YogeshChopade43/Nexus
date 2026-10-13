"""A calendar's ICS feed (the "secret address" Google Calendar, Outlook and iCloud give out): read-only events,
with repeating events expanded, in the user's timezone."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from app.integrations import base
from app.integrations.base import Field, IntegrationTool, Kind, strip_html

DEFAULT_DAYS = 7


def user_timezone() -> str:
    from app.api.routes.settings import user_timezone as saved  # imported late: the routes import this package

    return saved()

FIELDS = [Field("url", "Calendar feed address (ICS)", "password",
                help="Google Calendar: Settings › your calendar › Integrate calendar › Secret address in iCal format. "
                     "Outlook: Settings › Calendar › Shared calendars › Publish. iCloud: share the calendar publicly. "
                     "Treat it like a password: anyone with it can read the calendar.")]


async def _calendar(config: dict[str, Any]) -> icalendar.Calendar:
    text = await base.fetch_text(config["url"])
    try:
        return icalendar.Calendar.from_ical(text)
    except Exception as exc:  # not ICS at all (a login page, an HTML error)
        raise ValueError(f"That address didn't return a calendar (ICS): {exc}") from exc


def _when(value: str, zone: ZoneInfo, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)


def _iso(value: Any, zone: ZoneInfo) -> tuple[str, bool]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(zone).isoformat(), False
    if isinstance(value, date):
        return value.isoformat(), True
    return "", False


async def check(config: dict[str, Any]) -> str:
    calendar = await _calendar(config)
    events = len(calendar.walk("VEVENT"))
    name = str(calendar.get("X-WR-CALNAME") or "the calendar")
    return f"Found {events} event(s) in {name}"


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    async def list_events(p: dict[str, Any]) -> Any:
        zone = ZoneInfo(user_timezone() or "UTC")
        today = datetime.combine(datetime.now(zone).date(), time.min, tzinfo=zone)
        start = _when(str(p.get("start") or ""), zone, today)
        end = _when(str(p.get("end") or ""), zone, start + timedelta(days=DEFAULT_DAYS))
        if end <= start:
            end = start + timedelta(days=1)
        words = str(p.get("query") or "").lower()
        events = []
        for event in recurring_ical_events.of(await _calendar(config)).between(start, end):
            title = str(event.get("SUMMARY") or "(no title)")
            description = str(event.get("DESCRIPTION") or "")
            if words and words not in f"{title} {description}".lower():
                continue
            begins, all_day = _iso(event.get("DTSTART").dt, zone)
            ends, _ = _iso(event.get("DTEND").dt if event.get("DTEND") else event.get("DTSTART").dt, zone)
            events.append({"id": f"{event.get('UID')}@{begins}", "title": title, "start": begins, "end": ends,
                           "all_day": all_day, "location": str(event.get("LOCATION") or ""),
                           "description": strip_html(description, 300)})
        events.sort(key=lambda e: e["start"])
        return {"events": events, "timezone": str(zone)}

    return [IntegrationTool(slug, name, "list_events",
                            f"List events in the {name} calendar between two dates (default: the next {DEFAULT_DAYS} days), "
                            "repeating events included, optionally only those mentioning some words.", {
                                "properties": {"start": {"type": "string", "description": "ISO date or date-time"},
                                               "end": {"type": "string", "description": "ISO date or date-time"},
                                               "query": {"type": "string"}}},
                            list_events, title="List events")]


def prepare(config: dict[str, Any]) -> dict[str, Any]:
    """Calendar apps hand out webcal:// links: the same address over https."""
    return {**config, "url": re.sub(r"^webcals?://", "https://", str(config.get("url") or "").strip(), flags=re.IGNORECASE)}


KIND = Kind("calendar", "Calendar feed (ICS)", "See your Google, Outlook or iCloud calendar's events, read-only.",
            "CalendarDays", FIELDS, check, tools, prepare)

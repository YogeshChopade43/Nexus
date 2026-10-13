"""The daily briefing: a morning summary from the user's calendar, email, apps and feeds, sent to the bell and
their phone. It is an ordinary workflow (Ask the agent -> Notify), set up from one card."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.routes.settings import load_user_settings, update_user_settings
from app.workflows.scheduler import next_run_time

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

Section = Literal["calendar", "email", "apps", "feeds"]
SECTIONS: dict[str, str] = {
    "calendar": "Today's meetings and events from my calendar, with times in my timezone.",
    "email": "Important unread emails from the last day: who, what, and whether I need to reply. Skip newsletters, "
             "promotions and automatic notifications.",
    "apps": "What needs my attention in my apps today: issues and pull requests assigned to me, mentions, tasks due.",
    "feeds": "Notable new posts in my feeds since yesterday, one line each.",
}
NAME = "Daily briefing"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]


class BriefingIn(BaseModel):
    enabled: bool = True
    time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays_only: bool = True
    sections: list[Section] = Field(default_factory=lambda: list(SECTIONS))
    notes: str = Field(default="", max_length=500)


def prompt(sections: list[str], notes: str) -> str:
    wanted = "\n".join(f"- {SECTIONS[s]}" for s in SECTIONS if s in sections)
    return ("Prepare my daily briefing. Look things up in my connected apps; only read, change and send nothing.\n"
            f"Cover:\n{wanted}\n"
            "Keep it short and scannable: a heading per section, bullets, most important first. Leave a section out "
            "if there's nothing in it or no app for it; don't explain what's missing."
            + (f"\nAlso: {notes.strip()}" if notes.strip() else ""))


def _workflow(body: BriefingIn) -> dict[str, Any]:
    trigger = {"trigger_type": "recurrence", "frequency": "week" if body.weekdays_only else "day", "interval": 1,
               "at": body.time, **({"weekdays": WEEKDAYS} if body.weekdays_only else {})}
    return {
        "name": NAME, "description": "A morning summary of my calendar, email, apps and feeds, sent to my phone.",
        "isActive": body.enabled,
        "nodes": [
            {"id": "trigger_1", "type": "trigger", "name": "Trigger", "config": trigger},
            {"id": "brief", "type": "action", "name": "Write the briefing",
             "config": {"tool": "nexus__ask_agent", "parameters": {"prompt": prompt(body.sections, body.notes)}}},
            {"id": "send", "type": "action", "name": "Send it",
             "config": {"tool": "nexus__notify", "parameters": {"title": "Your daily briefing", "message": "{{ steps.brief.text }}"}}},
        ],
        "edges": [{"id": "e1", "source": "trigger_1", "target": "brief"}, {"id": "e2", "source": "brief", "target": "send"}],
    }


def _view(saved: dict[str, Any]) -> dict[str, Any]:
    from app.api.routes.workflows import get_workflow

    workflow_id, enabled = saved.get("workflowId"), False
    if workflow_id:
        try:
            enabled = get_workflow(workflow_id).isActive
        except Exception:  # deleted on the Workflows page: set up again from scratch
            workflow_id = None
    return {"enabled": enabled, "workflow_id": workflow_id, "time": saved.get("time", "08:00"),
            "weekdays_only": saved.get("weekdaysOnly", True), "sections": saved.get("sections", list(SECTIONS)),
            "notes": saved.get("notes", ""), "next_run_at": next_run_time(workflow_id) if workflow_id and enabled else None}


@router.get("")
def get_briefing() -> dict[str, Any]:
    return _view(load_user_settings().get("briefing") or {})


@router.put("")
def save_briefing(body: BriefingIn) -> dict[str, Any]:
    from app.api.routes.workflows import create_workflow, update_workflow
    from app.models.workflow import WorkflowCreate, WorkflowUpdate

    current = _view(load_user_settings().get("briefing") or {})
    spec = _workflow(body)
    if current["workflow_id"]:
        workflow = update_workflow(current["workflow_id"], WorkflowUpdate(**spec))
    else:
        workflow = create_workflow(WorkflowCreate(**spec))
    update_user_settings({"briefing": {"workflowId": workflow.id, "time": body.time, "weekdaysOnly": body.weekdays_only,
                                       "sections": list(body.sections), "notes": body.notes}})
    return get_briefing()


@router.post("/send-now")
async def send_now() -> dict[str, Any]:
    """Write and send one briefing right away (a preview of tomorrow's)."""
    from app.api.routes.agent import run_unattended
    from app.knowledge import Notify

    saved = load_user_settings().get("briefing") or {}
    text = await run_unattended(prompt(saved.get("sections") or list(SECTIONS), saved.get("notes") or ""))
    await Notify().execute({"title": "Your daily briefing", "message": text})
    return {"text": text}

"""Run-once workflows: a workflow that runs a single time, then stops.

Each has a trigger:
- ``at``: on a date and time. If Nexus was off then, it still runs up to CATCH_UP_WINDOW late; later than that it is
  marked missed and you're told, instead of (say) sending a birthday message days late.
- ``quiet``: if you go quiet for ``days`` days. "Checking in" is you using Nexus: a chat message (here or with the
  Telegram, Slack or Discord bot), an approval or answer, or "I'm here". It warns you daily from WARN_BEFORE early and
  never runs sooner than FINAL_NOTICE after the first warning, so after weeks with the computer off it warns first.

Each owns a workflow (in the "Run once" folder) for its steps; you fill it in with the usual editor.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, model_validator

from app.api.routes.settings import load_user_settings, update_user_settings
from app.core.database import get_connection, log_activity
from app.workflows.scheduler import CATCH_UP_WINDOW, _run_scheduled

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/run-once", tags=["run-once"])

MIN_DAYS, MAX_DAYS = 3, 365
WARN_BEFORE = timedelta(days=3)  # quiet: first warning this long before it would run
REMIND_EVERY = timedelta(days=1)
FINAL_NOTICE = timedelta(hours=48)  # quiet: never runs sooner than this after the first warning
FOLDER = "Run once"


class RunOnceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["at", "quiet"]
    at: Optional[datetime] = None
    days: Optional[int] = Field(default=None, ge=MIN_DAYS, le=MAX_DAYS)
    # What it does, one step after another (workflow nodes, without the trigger); more can be added in the editor.
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _when(self) -> "RunOnceIn":
        if self.kind == "at" and self.at is None:
            raise ValueError("Say when it should run (at)")
        if self.kind == "quiet" and self.days is None:
            self.days = 14
        return self


class RunOnceChange(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    enabled: Optional[bool] = None
    at: Optional[datetime] = None
    days: Optional[int] = Field(default=None, ge=MIN_DAYS, le=MAX_DAYS)


# ---- time and storage --------------------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if moment else None


def _time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def last_check_in() -> Optional[datetime]:
    return _time((load_user_settings().get("checkIn") or {}).get("last"))


def _rows() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT r.*, w.name AS name, w.nodes AS nodes, w.edges AS edges FROM run_once r "
                            "JOIN workflows w ON w.id = r.workflow_id ORDER BY r.id").fetchall()
        # A workflow deleted in the Workflows page takes its run-once with it.
        conn.execute("DELETE FROM run_once WHERE workflow_id NOT IN (SELECT id FROM workflows)")
        conn.commit()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _steps(row: dict[str, Any]) -> int:
    return sum(1 for node in json.loads(row.get("nodes") or "[]") if node.get("type") != "trigger")


# The "Note that it ran" step run-onces (and the digital will) used to start with: it messaged your phone.
PLACEHOLDER_MESSAGES = ("Your run-once workflow ran.", "Nexus didn't hear from you, so it carried out your instructions.")


def _is_placeholder(node: dict[str, Any]) -> bool:
    config = node.get("config") or {}
    return (node.get("id") == "tell" and config.get("tool") == "nexus__notify"
            and (config.get("parameters") or {}).get("message") in PLACEHOLDER_MESSAGES)


def _drop_placeholders() -> None:
    """Take that step out of existing run-onces, joining what came before it to what came after."""
    for row in _rows():
        nodes = json.loads(row.get("nodes") or "[]")
        gone = {n["id"] for n in nodes if _is_placeholder(n)}
        if not gone:
            continue
        edges = json.loads(row.get("edges") or "[]")
        sources = {node: [e["source"] for e in edges if e.get("target") == node] for node in gone}
        kept = []
        for edge in edges:
            if edge.get("target") in gone:
                continue
            if edge.get("source") in gone:
                kept += [{**edge, "source": source} for source in sources[edge["source"]]]
            else:
                kept.append(edge)
        conn = get_connection()
        try:
            conn.execute("UPDATE workflows SET nodes = ?, edges = ? WHERE id = ?",
                         (json.dumps([n for n in nodes if n["id"] not in gone]), json.dumps(kept), row["workflow_id"]))
            conn.commit()
        finally:
            conn.close()


def _row(item_id: int) -> dict[str, Any]:
    found = next((r for r in _rows() if r["id"] == item_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Run-once not found")
    return found


def _update(item_id: int, **changes: Any) -> None:
    conn = get_connection()
    try:
        conn.execute(f"UPDATE run_once SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?", [*changes.values(), item_id])
        conn.commit()
    finally:
        conn.close()


def _adopt_legacy_will() -> None:
    """The digital will (before run-once existed) becomes a "quiet" run-once, with its state."""
    will = load_user_settings().get("will") or {}
    workflow_id = will.get("workflowId")
    if not workflow_id:
        return
    conn = get_connection()
    try:
        exists = conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        adopted = conn.execute("SELECT 1 FROM run_once WHERE workflow_id = ?", (workflow_id,)).fetchone()
        if exists and not adopted:
            conn.execute(
                "INSERT INTO run_once (workflow_id, kind, days, enabled, armed_at, warned_at, reminded_at, ran_at, created_at) "
                "VALUES (?, 'quiet', ?, ?, ?, ?, ?, ?, ?)",
                (workflow_id, int(will.get("days") or 14), int(bool(will.get("enabled"))), will.get("lastCheckIn"),
                 will.get("warnedAt"), will.get("remindedAt"), will.get("triggeredAt"), _iso(_now())))
            conn.execute("UPDATE workflows SET folder = ? WHERE id = ?", (FOLDER, workflow_id))
            conn.commit()
    finally:
        conn.close()
    changes: dict[str, Any] = {"will": {"workflowId": None}}
    if will.get("lastCheckIn") and not last_check_in():
        changes["checkIn"] = {"last": will["lastCheckIn"]}
    update_user_settings(changes)


# ---- state --------------------------------------------------------------------------------------------------

def _quiet_since(row: dict[str, Any]) -> datetime:
    """Quiet from the later of your last check-in and when this one was set up (or re-armed)."""
    moments = [m for m in (last_check_in(), _time(row["armed_at"])) if m]
    return max(moments) if moments else _now()


def _view(row: dict[str, Any], now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or _now()
    warned = _time(row["warned_at"])
    if row["ran_at"]:
        status = "done"
    elif row["missed_at"]:
        status = "missed"
    elif not row["enabled"]:
        status = "off"
    elif row["kind"] == "at":
        status = "scheduled"
    else:
        status = "warning" if warned else "armed"
    runs_at = None
    if status == "scheduled":
        runs_at = _time(row["at"])
    elif status in ("armed", "warning"):
        runs_at = max(_quiet_since(row) + timedelta(days=int(row["days"])), (warned or now) + FINAL_NOTICE)
    return {"id": row["id"], "workflowId": row["workflow_id"], "name": row["name"], "kind": row["kind"],
            "at": row["at"], "days": row["days"], "enabled": bool(row["enabled"]), "status": status,
            "steps": _steps(row), "runsAt": _iso(runs_at), "quietSince": _iso(_quiet_since(row)) if row["kind"] == "quiet" else None,
            "warnedAt": row["warned_at"], "ranAt": row["ran_at"], "missedAt": row["missed_at"]}


def overview() -> dict[str, Any]:
    from app.integrations.channel import linked_channels

    _adopt_legacy_will()
    _drop_placeholders()
    channels = linked_channels()
    return {"items": [_view(row) for row in _rows()], "lastCheckIn": _iso(last_check_in()),
            "channels": sorted({c.NAME for c in channels})}  # where warnings reach you: Telegram, Slack, Discord


def check_in() -> None:
    """You're here: every "quiet" run-once starts its count again, and their warnings stop."""
    update_user_settings({"checkIn": {"last": _iso(_now())}})
    conn = get_connection()
    try:
        conn.execute("UPDATE run_once SET warned_at = NULL, reminded_at = NULL WHERE kind = 'quiet' AND ran_at IS NULL")
        conn.commit()
    finally:
        conn.close()


def refuse_manual_run(workflow_id: int, confirmed: bool) -> None:
    conn = get_connection()
    try:
        owned = conn.execute("SELECT 1 FROM run_once WHERE workflow_id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if owned and not confirmed:
        raise HTTPException(status_code=409, detail="This is a run once workflow: running it now really does everything "
                                                    "in it. Confirm to run it anyway.")


# ---- the minute-by-minute check -------------------------------------------------------------------------------

async def _tell(title: str, message: str) -> None:
    from app.integrations.telegram import notify_all

    log_activity("reminder", title, message)
    await notify_all(title, message)


async def _fire(row: dict[str, Any], now: datetime) -> str:
    _update(row["id"], ran_at=_iso(now), enabled=0)
    conn = get_connection()
    try:  # a switched-off workflow is skipped by the engine: a run-once must run regardless
        conn.execute("UPDATE workflows SET enabled = 1, is_active = 1 WHERE id = ?", (row["workflow_id"],))
        conn.commit()
    finally:
        conn.close()
    if not _steps(row):
        log_activity("run_once_ran", f"“{row['name']}” ran", "It had no steps yet, so nothing else happened.")
        return "ran"
    log_activity("run_once_ran", f"“{row['name']}” ran", "Run once" + (" after you went quiet" if row["kind"] == "quiet" else ""))
    await _run_scheduled(int(row["workflow_id"]), "run_once")
    return "ran"


async def _check(row: dict[str, Any], now: datetime) -> Optional[str]:
    if row["kind"] == "at":
        at = _time(row["at"])
        if not at or now < at:
            return None
        if now - at > CATCH_UP_WINDOW:  # far too late to do it now
            _update(row["id"], missed_at=_iso(now), enabled=0)
            await _tell(f"Missed: “{row['name']}”", f"It was due {_iso(at)} while Nexus was off, so it didn't run. "
                                                    "Pick a new time on the Run once page to run it.")
            return "missed"
        return await _fire(row, now)

    deadline = _quiet_since(row) + timedelta(days=int(row["days"]))
    if now < deadline - WARN_BEFORE:
        return None
    warned = _time(row["warned_at"])
    if warned and now >= deadline and now - warned >= FINAL_NOTICE:
        return await _fire(row, now)
    reminded = _time(row["reminded_at"])
    if not warned or not reminded or now - reminded >= REMIND_EVERY:
        _update(row["id"], warned_at=_iso(warned or now), reminded_at=_iso(now))
        left = max(deadline, (warned or now) + FINAL_NOTICE) - now
        when = "within a day" if left <= timedelta(days=1) else f"in about {round(left / timedelta(days=1))} days"
        await _tell(f"Are you OK? “{row['name']}” runs {when}",
                    "Nexus hasn't heard from you. Reply here, chat in Nexus, or press \"I'm here\" to stop it.")
        return "warned"
    return None


async def tick(now: Optional[datetime] = None) -> list[str]:
    """Check every run-once (each minute). Returns what happened: "ran", "warned", "missed"."""
    now = now or _now()
    _adopt_legacy_will()
    _drop_placeholders()
    done = []
    for row in _rows():
        if not row["enabled"] or row["ran_at"] or row["missed_at"]:
            continue
        try:
            if outcome := await _check(row, now):
                done.append(outcome)
        except Exception:  # one broken run-once must not stop the others
            logger.exception("Run-once %s failed", row["id"])
    return done


# ---- routes ---------------------------------------------------------------------------------------------------

@router.get("")
def list_run_once() -> dict[str, Any]:
    return overview()


@router.post("")
def create_run_once(body: RunOnceIn) -> dict[str, Any]:
    from app.api.routes.workflows import create_workflow
    from app.models.workflow import WorkflowCreate

    name = body.name.strip()
    steps = [n for n in body.nodes if n.get("type") != "trigger" and n.get("id") and n.get("id") != "trigger"]
    workflow = create_workflow(WorkflowCreate(
        name=name, folder=FOLDER, isActive=True,  # manual trigger: only its run-once (or a confirmed Run) runs it
        description="Runs once" + (" if you go quiet" if body.kind == "quiet" else " on its date") +
                    ": add what it should do, like an email or a Telegram message.",
        # Only the trigger: you add the steps. (Nexus notes in the bell that it ran; it never messages your phone itself.)
        nodes=[{"id": "trigger", "type": "trigger", "name": "When it's time", "config": {"trigger_type": "manual"}}, *steps],
        edges=[{"id": f"e{i}", "source": a["id"], "target": b["id"]}
               for i, (a, b) in enumerate(zip([{"id": "trigger"}, *steps], steps), start=1)],
    ))
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO run_once (workflow_id, kind, at, days, enabled, armed_at, created_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (workflow.id, body.kind, _iso(body.at), body.days if body.kind == "quiet" else None, _iso(_now()), _iso(_now())))
        conn.commit()
        item_id = cursor.lastrowid
    finally:
        conn.close()
    log_activity("run_once_set", f"Run once: “{name}”", "If you go quiet" if body.kind == "quiet" else f"On {_iso(body.at)}")
    return _view(_row(item_id))


@router.patch("/{item_id}")
def change_run_once(item_id: int, body: RunOnceChange) -> dict[str, Any]:
    row = _row(item_id)
    changes: dict[str, Any] = {}
    if body.at is not None and row["kind"] == "at":
        changes["at"] = _iso(body.at)
    if body.days is not None and row["kind"] == "quiet":
        changes["days"] = body.days
    if body.enabled is not None:
        changes["enabled"] = int(body.enabled)
    if body.enabled or changes.get("at") or changes.get("days"):
        # Switching on (or changing when) starts it afresh, also after it ran or was missed.
        changes.update(ran_at=None, missed_at=None, warned_at=None, reminded_at=None, armed_at=_iso(_now()))
        if body.enabled is None and not row["enabled"] and (row["ran_at"] or row["missed_at"]):
            changes["enabled"] = 1
    if changes:
        _update(item_id, **changes)
    if body.name and body.name.strip() != row["name"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE workflows SET name = ? WHERE id = ?", (body.name.strip(), row["workflow_id"]))
            conn.commit()
        finally:
            conn.close()
    return _view(_row(item_id))


@router.delete("/{item_id}", status_code=204)
def delete_run_once(item_id: int) -> Response:
    from app.api.routes.workflows import delete_workflow

    row = _row(item_id)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM run_once WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()
    delete_workflow(row["workflow_id"])
    return Response(status_code=204)


@router.post("/check-in")
def post_check_in() -> dict[str, Any]:
    check_in()
    return overview()

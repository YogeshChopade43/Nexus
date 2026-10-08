"""Numbers for the run dashboard: runs per day, failures, slowest steps and AI token use."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

from app.core.database import get_connection
from app.llm.metering import tokens_used_today

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/")
def dashboard(days: int = Query(14, ge=1, le=90)) -> dict[str, Any]:
    from app.api.routes.settings import load_user_settings

    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    since = start.isoformat()
    dates = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    conn = get_connection()
    try:
        runs = conn.execute(
            "SELECT workflow_runs.status, workflow_runs.started_at, workflow_runs.events, workflows.name, workflows.id AS wid "
            "FROM workflow_runs JOIN workflows ON workflows.id = workflow_runs.workflow_id WHERE started_at >= ?",
            (since,),
        ).fetchall()
        usage = conn.execute(
            "SELECT substr(timestamp, 1, 10) AS day, model, SUM(input_tokens) AS input, SUM(output_tokens) AS output, "
            "MAX(estimated) AS estimated FROM llm_usage WHERE timestamp >= ? GROUP BY day, model",
            (since,),
        ).fetchall()
    finally:
        conn.close()

    per_day = {d: {"date": d, "completed": 0, "failed": 0, "other": 0} for d in dates}
    failures: dict[int, dict[str, Any]] = {}
    step_times: dict[tuple[int, str], list[int]] = defaultdict(list)
    step_names: dict[tuple[int, str], tuple[str, str]] = {}
    for run in runs:
        day = per_day.get(run["started_at"][:10])
        status = run["status"] if run["status"] in ("completed", "failed") else "other"
        if day:
            day[status] += 1
        if run["status"] == "failed":
            entry = failures.setdefault(run["wid"], {"workflow_id": run["wid"], "name": run["name"], "failures": 0})
            entry["failures"] += 1
        try:
            events = json.loads(run["events"] or "[]")
        except (json.JSONDecodeError, TypeError):
            events = []
        for event in events:
            if isinstance(event, dict) and event.get("duration") is not None and event.get("nodeId") and not event.get("reused"):
                key = (run["wid"], event["nodeId"])
                step_times[key].append(int(event["duration"]))
                step_names[key] = (run["name"], event.get("nodeName") or event["nodeId"])

    slowest = sorted(
        ({"workflow_id": wid, "workflow": step_names[(wid, node)][0], "step": step_names[(wid, node)][1],
          "average_ms": sum(times) // len(times), "max_ms": max(times), "runs": len(times)}
         for (wid, node), times in step_times.items()),
        key=lambda s: s["average_ms"], reverse=True,
    )[:8]

    prices = load_user_settings().get("llmPrices") or {}
    tokens_per_day = {d: {"date": d, "input": 0, "output": 0} for d in dates}
    by_model: dict[str, dict[str, Any]] = {}
    for row in usage:
        if row["day"] in tokens_per_day:
            tokens_per_day[row["day"]]["input"] += row["input"]
            tokens_per_day[row["day"]]["output"] += row["output"]
        model = by_model.setdefault(row["model"], {"model": row["model"], "input": 0, "output": 0, "estimated": False})
        model["input"] += row["input"]
        model["output"] += row["output"]
        model["estimated"] = model["estimated"] or bool(row["estimated"])
    for model in by_model.values():
        price = prices.get(model["model"])
        model["cost"] = (
            round((model["input"] * float(price.get("input") or 0) + model["output"] * float(price.get("output") or 0)) / 1_000_000, 4)
            if isinstance(price, dict) else None
        )

    total = len(runs)
    failed = sum(1 for r in runs if r["status"] == "failed")
    return {
        "days": days,
        "runs_per_day": list(per_day.values()),
        "total_runs": total,
        "failed_runs": failed,
        "failure_rate": round(failed / total, 3) if total else 0,
        "top_failing": sorted(failures.values(), key=lambda f: f["failures"], reverse=True)[:5],
        "slowest_steps": slowest,
        "tokens_per_day": list(tokens_per_day.values()),
        "tokens_by_model": sorted(by_model.values(), key=lambda m: m["input"] + m["output"], reverse=True),
        "tokens_today": tokens_used_today(),
        "daily_token_limit": int(load_user_settings().get("dailyTokenLimit") or 0),
    }

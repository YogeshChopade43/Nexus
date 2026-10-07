"""Workflow execution engine.

A workflow is a DAG of nodes joined by edges. Nodes run in topological order; a node
runs when at least one incoming edge is active (or it has no incoming edges). Node
parameters are Jinja2 templates rendered in a sandbox against the run context:

    {{ input.x }}                 run input
    {{ trigger.payload.action }}  trigger data (webhook body, schedule tick, app event)
    {{ steps.<node_id>.<field> }} output of an earlier node

A parameter that is exactly one ``{{ expression }}`` keeps its native type (list,
dict, number), so whole objects can be passed between steps.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from jinja2 import Undefined
from jinja2.sandbox import SandboxedEnvironment

from app.core.database import get_connection, log_activity
from app.models.workflow import WorkflowRunRequest, WorkflowRunResult
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

NODE_TYPES = {"trigger", "action", "tool", "llm", "condition", "transform", "delay", "output"}
CONDITION_OPERATORS = {
    "truthy", "falsy", "equals", "not_equals", "contains", "not_contains",
    "gt", "gte", "lt", "lte", "is_empty", "not_empty",
}
MAX_RETRIES = 5
MAX_DELAY_SECONDS = 300

class _TemplateEnvironment(SandboxedEnvironment):
    """``steps.a.items`` must mean the key ``items``, not ``dict.items``: prefer keys over attributes."""

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, dict) and attribute in obj:
            return obj[attribute]
        return super().getattr(obj, attribute)


_env = _TemplateEnvironment(undefined=Undefined, autoescape=False)
_env.filters["tojson"] = lambda value: json.dumps(value, default=str)
_SINGLE_EXPR = re.compile(r"^\s*\{\{(.+?)\}\}\s*$", re.DOTALL)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------

def render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render templates inside strings, dicts and lists. Non-template values pass through."""
    if isinstance(value, str):
        if "{{" not in value and "{%" not in value:
            return value
        match = _SINGLE_EXPR.match(value)
        if match and "{{" not in match.group(1):
            result = _env.compile_expression(match.group(1).strip(), undefined_to_none=True)(**context)
            return result
        return _env.from_string(value).render(**context)
    if isinstance(value, dict):
        return {key: render_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    return value


def _lookup(path: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted path (``steps.n1.count``) or a ``{{ expression }}`` against the context."""
    if "{{" in str(path):
        return render_value(path, context)
    value: Any = context
    for key in str(path).split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def _coerce(expected: Any, actual: Any) -> Any:
    """Compare numbers with numbers even when the UI stored the value as text."""
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, str):
        try:
            return float(expected)
        except ValueError:
            return expected
    return expected


def evaluate_condition(config: dict[str, Any], context: dict[str, Any]) -> bool:
    operator = config.get("operator") or "truthy"
    value = _lookup(config.get("field") or "", context)
    expected = config.get("value")
    if isinstance(expected, str) and "{{" in expected:
        expected = render_value(expected, context)
    expected = _coerce(expected, value)
    try:
        if operator == "truthy":
            return bool(value)
        if operator == "falsy":
            return not value
        if operator == "equals":
            return value == expected or str(value) == str(expected)
        if operator == "not_equals":
            return not (value == expected or str(value) == str(expected))
        if operator == "contains":
            return expected in value
        if operator == "not_contains":
            return expected not in value
        if operator == "gt":
            return value > expected
        if operator == "gte":
            return value >= expected
        if operator == "lt":
            return value < expected
        if operator == "lte":
            return value <= expected
        if operator == "is_empty":
            return value in (None, "", [], {})
        if operator == "not_empty":
            return value not in (None, "", [], {})
    except TypeError:
        return False
    return bool(value)


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _node_type(node: dict[str, Any]) -> str:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    node_type = node.get("type") or config.get("type") or "action"
    return "action" if node_type == "tool" else node_type


def _node_config(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("config") if isinstance(node.get("config"), dict) else {}


def nodes_from_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert the legacy linear ``steps`` format into a chain of nodes."""
    nodes, edges = [], []
    for index, step in enumerate(steps):
        node_id = str(step.get("node_id") or step.get("id") or f"step-{index + 1}")
        step_type = step.get("type") or "action"
        config = {k: v for k, v in step.items() if k not in ("node_id", "id", "node_name", "name", "type")}
        if step_type in ("tool", "action") and "tool" not in config and "app" in config and "action" in config:
            config["tool"] = f"{config['app']}_{config['action']}"
        if "params" in config and "parameters" not in config:
            config["parameters"] = config.pop("params")
        nodes.append({"id": node_id, "type": step_type, "name": step.get("node_name") or step.get("name") or node_id, "config": config})
        if index:
            edges.append({"id": f"edge-{index}", "source": nodes[index - 1]["id"], "target": node_id})
    return nodes, edges


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Optional[list[str]]:
    """Node ids in dependency order, or ``None`` when the graph has a cycle."""
    ids = [str(node.get("id")) for node in nodes]
    indegree = {node_id: 0 for node_id in ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in outgoing and target in indegree and source != target:
            outgoing[source].append(target)
            indegree[target] += 1
    ready = [node_id for node_id in ids if indegree[node_id] == 0]
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return order if len(order) == len(ids) else None


def validate_workflow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    tool_registry: Optional[ToolRegistry] = None,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block saving; warnings describe nodes that will fail."""
    errors: list[str] = []
    warnings: list[str] = []
    ids = [str(node.get("id", "")) for node in nodes]
    if len(set(ids)) != len(ids) or "" in ids:
        errors.append("Every node needs a unique id")
    node_ids = set(ids)
    for edge in edges:
        if str(edge.get("source")) not in node_ids or str(edge.get("target")) not in node_ids:
            errors.append(f"Edge {edge.get('id', '?')} references a missing node")
    if topological_order(nodes, edges) is None:
        errors.append("The workflow contains a cycle")
    if sum(1 for node in nodes if _node_type(node) == "trigger") > 1:
        errors.append("A workflow can have only one trigger node")

    for node in nodes:
        node_type = _node_type(node)
        config = _node_config(node)
        label = node.get("name") or node.get("id")
        if node_type not in NODE_TYPES:
            errors.append(f"Node '{label}' has unknown type '{node_type}'")
        elif node_type == "action":
            tool_name = config.get("tool")
            if not tool_name:
                warnings.append(f"Action '{label}' has no tool selected")
            elif tool_registry is not None:
                try:
                    tool_registry.get_tool(tool_name)
                except Exception:
                    warnings.append(f"Action '{label}' uses unknown tool '{tool_name}'")
        elif node_type == "llm" and not config.get("prompt"):
            warnings.append(f"LLM node '{label}' has no prompt")
        elif node_type == "condition":
            if config.get("operator", "truthy") not in CONDITION_OPERATORS:
                errors.append(f"Condition '{label}' has unknown operator '{config.get('operator')}'")
            if not config.get("field"):
                warnings.append(f"Condition '{label}' has no field to check")
        for template_field in ("prompt", "template"):
            if isinstance(config.get(template_field), str):
                try:
                    _env.parse(config[template_field])
                except Exception as exc:
                    errors.append(f"Node '{label}' has an invalid {template_field}: {exc}")
    return errors, warnings


# ---------------------------------------------------------------------------
# Node execution
# ---------------------------------------------------------------------------

def _sanitize(value: Any) -> Any:
    sensitive = ("password", "secret", "token", "api_key", "apikey", "credential", "private_key")
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if not any(f in str(k).lower() for f in sensitive)}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _resolve_llm_provider(provider_id: Any, workflow_provider_id: Any) -> Any:
    from app.llm.utils import get_active_llm_provider, get_default_llm_provider

    for candidate in (provider_id, workflow_provider_id):
        if candidate:
            try:
                provider, _ = get_active_llm_provider(provider_id=int(candidate))
                return provider
            except Exception as exc:
                logger.warning("Workflow LLM provider %s unavailable: %s", candidate, exc)
    try:
        provider, _ = get_default_llm_provider()
        return provider
    except Exception:
        return None


async def _run_action(config, context, tool_registry, app_connections) -> dict[str, Any]:
    tool_name = config.get("tool")
    if not tool_name and config.get("app") and config.get("action"):
        tool_name = f"{config['app']}_{config['action']}"
    if not tool_name:
        raise ValueError("No tool selected for this action")
    tool = tool_registry.get_tool(tool_name)
    if not app_connections.get(tool.app_id, False):
        raise PermissionError(f"App '{tool.app_id}' is not connected")
    parameters = render_value(config.get("parameters") or config.get("params") or {}, context)
    if not isinstance(parameters, dict):
        raise ValueError("Action parameters must be an object")
    parameters = {k: v for k, v in parameters.items() if v not in (None, "")}
    result = await tool.execute(parameters)
    return {"input": parameters, "output": result if isinstance(result, dict) else {"result": result}, "app_id": tool.app_id, "tool": tool_name}


async def _run_llm(config, context, workflow_provider_id) -> dict[str, Any]:
    provider = _resolve_llm_provider(config.get("provider_id"), workflow_provider_id)
    if provider is None:
        raise RuntimeError("No LLM provider configured. Add one in Settings > AI.")
    prompt = render_value(config.get("prompt") or "", context)
    if not isinstance(prompt, str):
        prompt = json.dumps(prompt, default=str)
    if not prompt.strip():
        raise ValueError("LLM prompt is empty")
    messages = [
        {"role": "system", "content": config.get("system") or "You are Nexus, an automation assistant. Respond concisely."},
        {"role": "user", "content": prompt},
    ]
    result = await provider.chat(messages=messages, model=config.get("model") or "")
    content = result.get("content", "")
    return {
        "input": {"prompt": prompt},
        "output": {config.get("output_key") or "text": content, "text": content, "model": result.get("model", "")},
    }


def _run_transform(config, context) -> dict[str, Any]:
    rendered = render_value(config.get("template", ""), context)
    if isinstance(rendered, str):
        try:
            rendered = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            pass
    return {"output": {config.get("output_key") or "value": rendered, "value": rendered}}


async def _with_retries(func, retries: int):
    attempt = 0
    while True:
        try:
            return await func(), attempt
        except (PermissionError, ValueError):
            raise  # configuration problems will not fix themselves on retry
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            await asyncio.sleep(min(2 ** (attempt - 1), 10))


# ---------------------------------------------------------------------------
# Run persistence
# ---------------------------------------------------------------------------

def _insert_run(run_id: str, workflow_id: int, started_at: str, input_data: dict[str, Any]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_id, status, started_at, input_data) VALUES (?, ?, 'running', ?, ?)",
            (run_id, workflow_id, started_at, json.dumps(input_data, default=str)),
        )
        conn.commit()
    finally:
        conn.close()


def _finish_run(result: WorkflowRunResult, steps: list[dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE workflow_runs SET status = ?, completed_at = ?, output = ?, error = ?, events = ?, trace = ?
            WHERE id = ?
            """,
            (
                result.status,
                result.completed_at,
                json.dumps(result.output, default=str),
                result.error,
                json.dumps(result.events, default=str),
                json.dumps(result.trace, default=str),
                result.id,
            ),
        )
        for step in steps:
            conn.execute(
                """
                INSERT INTO workflow_run_steps
                    (run_id, workflow_id, node_id, node_name, node_type, tool_name, status, started_at,
                     completed_at, input_data, output_data, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.id, result.workflow_id, step["nodeId"], step["nodeName"], step["type"],
                    step.get("tool"), step["status"], step["timestamp"], step.get("completedAt"),
                    json.dumps(step.get("input", {}), default=str), json.dumps(step.get("output", {}), default=str),
                    step.get("error"),
                ),
            )
        conn.execute("UPDATE workflows SET last_run = ? WHERE id = ?", (result.completed_at, result.workflow_id))
        conn.commit()
    finally:
        conn.close()


def mark_interrupted_runs() -> None:
    """Runs left 'running' by a crash or restart can never finish; mark them failed."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE workflow_runs SET status = 'failed', error = 'Interrupted by server restart', "
            "completed_at = ? WHERE status = 'running'",
            (_utc_now(),),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def load_workflow_graph(row: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = _load_list(row["nodes"])
    edges = _load_list(row["edges"])
    if not nodes:
        nodes, edges = nodes_from_steps(_load_list(row["steps"]))
    return nodes, edges


async def run_workflow(
    workflow_id: int,
    tool_registry: ToolRegistry,
    app_connections: dict[str, bool],
    req: WorkflowRunRequest,
    trigger: Optional[dict[str, Any]] = None,
) -> WorkflowRunResult:
    started_at = _utc_now()
    run_id = str(uuid4())
    input_data = dict(req.input_data or {})

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Workflow not found")

    nodes, edges = load_workflow_graph(row)
    workflow_name = row["name"]
    trigger = trigger or {"type": "manual"}
    run_input = input_data if trigger == {"type": "manual"} else {**input_data, "trigger": trigger}
    _insert_run(run_id, workflow_id, started_at, run_input)

    events: list[dict[str, Any]] = []
    status, first_error = "completed", None
    final_output: dict[str, Any] = {}

    if not (row["enabled"] and row["is_active"]):
        status, first_error = "skipped", "Workflow is disabled"
        events.append({"id": "workflow-disabled", "nodeId": "workflow", "nodeName": "Workflow", "type": "conditional",
                       "status": "skipped", "timestamp": started_at, "step": 0, "error": first_error})
    elif not any(_node_type(node) != "trigger" for node in nodes):
        status, first_error = "failed", "Workflow has no steps to run"
    else:
        order = topological_order(nodes, edges)
        if order is None:
            status, first_error = "failed", "The workflow contains a cycle"
        else:
            status, first_error, final_output = await _execute_graph(
                nodes, edges, order, input_data, trigger, tool_registry, app_connections,
                row["llm_provider_id"], events,
            )

    completed_at = _utc_now()
    result = WorkflowRunResult(
        id=run_id,
        workflow_id=workflow_id,
        workflowId=str(workflow_id),
        status=status,
        started_at=started_at,
        startedAt=started_at,
        completed_at=completed_at,
        completedAt=completed_at,
        input_data=run_input,
        input=run_input,
        output={"result": final_output, "steps": [
            {"step": e["step"], "nodeId": e["nodeId"], "tool": e.get("tool"), "status": e["status"], "data": e.get("output", {})}
            for e in events if e.get("step")
        ]},
        error=first_error,
        events=events,
        trace=events,
        duration_ms=int((datetime.fromisoformat(completed_at[:-1]) - datetime.fromisoformat(started_at[:-1])).total_seconds() * 1000),
    )
    _finish_run(result, [e for e in events if e.get("step")])
    log_activity(
        "workflow_completed" if status in ("completed", "partial") else "workflow_failed",
        f"Workflow '{workflow_name}' {status}",
        first_error or f"{sum(1 for e in events if e['status'] == 'success')} step(s) succeeded",
        {"workflow_id": workflow_id, "run_id": run_id, "status": status, "trigger": trigger.get("type")},
    )
    return result


async def _execute_graph(
    nodes, edges, order, input_data, trigger, tool_registry, app_connections, workflow_provider_id, events,
) -> tuple[str, Optional[str], dict[str, Any]]:
    by_id = {str(node["id"]): node for node in nodes}
    incoming: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in by_id}
    for edge in edges:
        if str(edge.get("target")) in incoming:
            incoming[str(edge["target"])].append(edge)

    context: dict[str, Any] = {"input": input_data, "trigger": trigger, "steps": {}}
    outcome: dict[str, str] = {}           # node_id -> success | failed | skipped
    branch: dict[str, bool] = {}           # condition node_id -> result
    status, first_error = "completed", None
    final_output: dict[str, Any] = {}
    halted = False
    step_number = 0

    def edge_active(edge: dict[str, Any]) -> bool:
        source = str(edge.get("source"))
        if outcome.get(source) != "success":
            return False
        if source in branch:
            label = str(edge.get("sourceHandle") or edge.get("condition") or edge.get("label") or "true").lower()
            wants_true = label not in ("false", "else", "no")
            return branch[source] == wants_true
        return True

    for node_id in order:
        node = by_id[node_id]
        node_type = _node_type(node)
        config = _node_config(node)
        name = node.get("name") or node_id

        if node_type == "trigger":
            outcome[node_id] = "success"
            context["steps"][node_id] = trigger
            continue

        step_number += 1
        event: dict[str, Any] = {
            "id": f"step-{step_number}", "nodeId": node_id, "nodeName": name, "type": node_type,
            "timestamp": _utc_now(), "step": step_number, "status": "success",
        }
        events.append(event)

        if halted or (incoming[node_id] and not any(edge_active(e) for e in incoming[node_id])):
            outcome[node_id] = event["status"] = "skipped"
            event["type"] = "conditional"
            event["reason"] = "Previous step failed" if halted else "Branch not taken"
            continue

        started = time.perf_counter()
        retries = max(0, min(int(config.get("retries") or 0), MAX_RETRIES))
        try:
            if node_type == "action":
                result, attempts = await _with_retries(
                    lambda: _run_action(config, context, tool_registry, app_connections), retries
                )
                event.update({"tool": result["tool"], "tool_name": result["tool"], "app_id": result["app_id"], "connected": True})
            elif node_type == "llm":
                result, attempts = await _with_retries(lambda: _run_llm(config, context, workflow_provider_id), retries)
            elif node_type == "condition":
                branch[node_id] = evaluate_condition(config, context)
                result, attempts = {"output": {"result": branch[node_id]}}, 0
                event["condition"] = branch[node_id]
            elif node_type == "transform":
                result, attempts = _run_transform(config, context), 0
            elif node_type == "delay":
                seconds = max(0.0, min(float(config.get("seconds") or 0), MAX_DELAY_SECONDS))
                await asyncio.sleep(seconds)
                result, attempts = {"output": {"waited_seconds": seconds}}, 0
            else:  # output
                value = render_value(config.get("template"), context) if config.get("template") else context["steps"]
                final_output = value if isinstance(value, dict) else {"value": value}
                result, attempts = {"output": final_output}, 0
            event["input"] = _sanitize(result.get("input", {}))
            event["output"] = event["data"] = _sanitize(result["output"])
            event["attempts"] = attempts + 1
            context["steps"][node_id] = result["output"]
            outcome[node_id] = "success"
            if node_type == "action":
                event["type"] = "tool_executed"
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            event.update({"status": "failed", "type": "error", "error": message})
            if isinstance(exc, PermissionError):
                event["connected"] = False
            first_error = first_error or f"{name}: {message}"
            if config.get("continue_on_error"):
                # Downstream steps still run; they see an empty output for this node.
                outcome[node_id] = "success"
                context["steps"][node_id] = {"error": message}
                status = "partial"
            else:
                outcome[node_id] = "failed"
                status = "failed"
                halted = True
        event["duration"] = int((time.perf_counter() - started) * 1000)
        event["completedAt"] = _utc_now()

    if not final_output:
        last = next((e for e in reversed(events) if e["status"] == "success" and e.get("output") is not None), None)
        final_output = last["output"] if last else {}
    return status, first_error, final_output


def demo() -> None:
    """Self-check for templating, conditions and ordering: ``python -m app.workflows.engine``."""
    ctx = {"input": {"n": 3}, "steps": {"a": {"items": [1, 2], "title": "x"}}}
    assert render_value("{{ steps.a.items }}", ctx) == [1, 2]
    assert render_value("count={{ steps.a.items | length }}", ctx) == "count=2"
    assert render_value({"q": ["{{ input.n }}"]}, ctx) == {"q": [3]}
    assert evaluate_condition({"field": "input.n", "operator": "gt", "value": "2"}, ctx)
    assert not evaluate_condition({"field": "steps.a.missing", "operator": "truthy"}, ctx)
    assert topological_order([{"id": "a"}, {"id": "b"}], [{"source": "b", "target": "a"}]) == ["b", "a"]
    assert topological_order([{"id": "a"}, {"id": "b"}], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]) is None
    print("engine self-check passed")


if __name__ == "__main__":
    demo()

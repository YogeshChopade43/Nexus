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
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import uuid4

import httpx

from jinja2 import Undefined
from jinja2.sandbox import SandboxedEnvironment

from app.core.database import get_connection, log_activity
from app.models.workflow import WorkflowRunRequest, WorkflowRunResult
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

NODE_TYPES = {"trigger", "action", "tool", "llm", "condition", "transform", "delay", "output",
              "http", "code", "workflow", "loop", "parallel"}
CONDITION_OPERATORS = {
    "truthy", "falsy", "equals", "not_equals", "contains", "not_contains",
    "gt", "gte", "lt", "lte", "is_empty", "not_empty",
}
MAX_RETRIES = 5
MAX_DELAY_SECONDS = 300
DEFAULT_STEP_TIMEOUT = 300  # seconds; container steps (loop, parallel, sub-workflow) have none by default
MAX_LOOP_ITEMS = 500
MAX_WORKFLOW_DEPTH = 5
CODE_TIME_LIMIT = 5  # seconds of JavaScript CPU time
CODE_MEMORY_LIMIT = 32 * 1024 * 1024

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


def _load_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
    all_ids = [str(node.get("id", "")) for node in iter_all_nodes(nodes)]
    if len(set(all_ids)) != len(all_ids) or "" in all_ids:
        errors.append("Every node needs a unique id (including steps inside loops, branches and error handlers)")
    _validate_graph(nodes, edges, tool_registry, errors, warnings, top_level=True)
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def nested_graphs(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Sub-workflows held inside a node: a loop body, parallel branches, an error handler."""
    config = _node_config(node)
    graphs = [config.get("body"), config.get("on_error"), *(config.get("branches") or [])]
    return [g for g in graphs if isinstance(g, dict)]


def iter_all_nodes(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        for graph in nested_graphs(node):
            yield from iter_all_nodes(graph.get("nodes") or [])


def _validate_graph(nodes, edges, tool_registry, errors, warnings, top_level=False) -> None:
    ids = [str(node.get("id", "")) for node in nodes]
    node_ids = set(ids)
    for edge in edges:
        if str(edge.get("source")) not in node_ids or str(edge.get("target")) not in node_ids:
            errors.append(f"Edge {edge.get('id', '?')} references a missing node")
    if topological_order(nodes, edges) is None:
        errors.append("The workflow contains a cycle")
    if sum(1 for node in nodes if _node_type(node) == "trigger") > (1 if top_level else 0):
        errors.append("A workflow can have only one trigger node, at the top level")

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
        elif node_type == "http" and not config.get("url"):
            warnings.append(f"HTTP step '{label}' has no URL")
        elif node_type == "code" and not str(config.get("code") or "").strip():
            warnings.append(f"Code step '{label}' is empty")
        elif node_type == "workflow" and not config.get("workflow_id"):
            warnings.append(f"Sub-workflow step '{label}' has no workflow selected")
        elif node_type == "loop" and not config.get("items"):
            warnings.append(f"Loop '{label}' has no list to loop over")
        for template_field in ("prompt", "template"):
            if isinstance(config.get(template_field), str):
                try:
                    _env.parse(config[template_field])
                except Exception as exc:
                    errors.append(f"Node '{label}' has an invalid {template_field}: {exc}")
        for graph in nested_graphs(node):
            _validate_graph(graph.get("nodes") or [], graph.get("edges") or [], tool_registry, errors, warnings)


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
    from app.auth.owner import owns_app

    if not owns_app(tool.app_id) or not app_connections.get(tool.app_id, False):  # someone else's app: never
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


RESUME_WINDOW = timedelta(hours=24)  # older interrupted runs are left failed, not resumed


def mark_interrupted_runs() -> list[dict[str, Any]]:
    """Runs left 'running' by a crash or restart can never finish: mark them failed.

    Returns the recent ones so they can be resumed once the MCP servers are back.
    """
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, workflow_id, started_at, input_data, events FROM workflow_runs WHERE status = 'running'"
        ).fetchall()]
        conn.execute(
            "UPDATE workflow_runs SET status = 'failed', error = 'Interrupted by server restart', "
            "completed_at = ? WHERE status = 'running'",
            (_utc_now(),),
        )
        conn.commit()
    finally:
        conn.close()
    cutoff = (datetime.now(timezone.utc) - RESUME_WINDOW).isoformat().replace("+00:00", "Z")
    return [row for row in rows if row["started_at"] >= cutoff]


async def resume_interrupted_runs(
    runs: list[dict[str, Any]], tool_registry: ToolRegistry, app_connections: Callable[[], dict[str, bool]],
) -> None:
    """Start each interrupted run again, reusing the outputs of the steps it had finished.

    The step that was in progress when Nexus stopped runs again.
    """
    for run in runs:
        input_data = _load_dict(run["input_data"])
        trigger = input_data.pop("trigger", None)
        try:
            new_id = start_background_run(
                run["workflow_id"], tool_registry, app_connections(), WorkflowRunRequest(input_data=input_data),
                trigger=trigger, reuse=reusable_outputs(_load_list(run["events"])),
            )
        except Exception:
            logger.exception("Could not resume run %s", run["id"])
            continue
        conn = get_connection()
        try:
            conn.execute("UPDATE workflow_runs SET error = ? WHERE id = ?",
                         (f"Interrupted by server restart; resumed as run {new_id}", run["id"]))
            conn.commit()
        finally:
            conn.close()
        log_activity("workflow_resumed", "Resumed a workflow run interrupted by a restart",
                     metadata={"workflow_id": run["workflow_id"], "run_id": new_id, "previous_run_id": run["id"]})


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def load_workflow_graph(row: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = _load_list(row["nodes"])
    edges = _load_list(row["edges"])
    if not nodes:
        nodes, edges = nodes_from_steps(_load_list(row["steps"]))
    return nodes, edges


def _update_progress(run_id: str, events: list[dict[str, Any]]) -> None:
    """Write the trace so far, so a run can be watched while it executes."""
    conn = get_connection()
    try:
        payload = json.dumps(events, default=str)
        conn.execute("UPDATE workflow_runs SET events = ?, trace = ? WHERE id = ?", (payload, payload, run_id))
        conn.commit()
    finally:
        conn.close()


@dataclass
class RunState:
    tool_registry: ToolRegistry
    app_connections: dict[str, bool]
    workflow_provider_id: Any = None
    run_id: str = ""
    depth: int = 0
    reuse: dict[str, Any] = field(default_factory=dict)  # node_id -> output from an earlier run
    events: list[dict[str, Any]] = field(default_factory=list)
    counter: list[int] = field(default_factory=lambda: [0])
    progress: Optional[Callable[[], None]] = None


# ---- per-type executors (each returns {"input": ..., "output": ...}) ---------------

async def _run_http(config, context) -> dict[str, Any]:
    method = str(config.get("method") or "GET").upper()
    url = render_value(config.get("url") or "", context)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("HTTP step needs an http(s) URL")
    headers = {str(k): str(v) for k, v in (render_value(config.get("headers") or {}, context) or {}).items()}
    body = render_value(config.get("body"), context) if config.get("body") not in (None, "") else None
    kwargs: dict[str, Any] = {"headers": headers}
    if isinstance(body, (dict, list)):
        kwargs["json"] = body
    elif body is not None:
        kwargs["content"] = str(body)
    from app.integrations.web import guard_request

    async with httpx.AsyncClient(timeout=float(config.get("request_timeout") or 30), follow_redirects=True,
                                 event_hooks={"request": [guard_request]}) as client:
        response = await client.request(method, url, **kwargs)
    try:
        data: Any = response.json()
        output: dict[str, Any] = {"status": response.status_code, "data": data}
    except ValueError:
        output = {"status": response.status_code, "text": response.text[:100_000]}
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code} from {url}: {response.text[:200]}")
    return {"input": {"method": method, "url": url}, "output": output}


def _run_code_sync(code: str, payload: str) -> Any:
    import quickjs

    ctx = quickjs.Context()  # no require/fetch/filesystem: pure JavaScript only
    ctx.set_time_limit(CODE_TIME_LIMIT)
    ctx.set_memory_limit(CODE_MEMORY_LIMIT)
    try:
        result = ctx.eval(f"JSON.stringify((function (input) {{\n{code}\n}})({payload}))")
    except quickjs.JSException as exc:
        message = str(exc)
        if "interrupted" in message:
            raise RuntimeError(f"Code step timed out after {CODE_TIME_LIMIT}s")
        raise RuntimeError(f"Code error: {message.splitlines()[0]}")
    return None if result is None else json.loads(result)


async def _run_code(config, context) -> dict[str, Any]:
    code = str(config.get("code") or "")
    payload = json.dumps({k: context.get(k) for k in ("input", "trigger", "steps", "loop", "error")}, default=str)
    value = await asyncio.to_thread(_run_code_sync, code, payload)
    return {"output": {"value": value}}


async def _run_subworkflow(config, context, state: RunState) -> dict[str, Any]:
    if state.depth >= MAX_WORKFLOW_DEPTH:
        raise RuntimeError(f"Sub-workflows are nested too deep (max {MAX_WORKFLOW_DEPTH})")
    workflow_id = int(config.get("workflow_id") or 0)
    values = render_value(config.get("inputs") or {}, context)
    child = await run_workflow(
        workflow_id, state.tool_registry, state.app_connections, WorkflowRunRequest(input_data=values),
        trigger={"type": "manual", "inputs": values}, depth=state.depth + 1,
    )
    output = {"status": child.status, "run_id": child.id, "result": child.output.get("result", {})}
    if child.status == "failed":
        raise RuntimeError(f"Sub-workflow failed: {child.error}")
    return {"input": values, "output": output}


async def _run_loop(node_id, config, context, state: RunState) -> dict[str, Any]:
    items = render_value(config.get("items"), context)
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            pass
    if not isinstance(items, list):
        raise ValueError("Loop items must be a list (for example {{ steps.action_1.data.items }})")
    if len(items) > MAX_LOOP_ITEMS:
        raise ValueError(f"Loop has {len(items)} items; the limit is {MAX_LOOP_ITEMS}")
    graph = config.get("body") or {}
    outer = context.get("loop")
    results = []
    try:
        for index, item in enumerate(items):
            context["loop"] = {"item": item, "index": index}
            status, error, final = await _execute_graph(
                graph.get("nodes") or [], graph.get("edges") or [], context, state, parent=node_id, label=f"item {index + 1}",
            )
            if status == "failed":
                raise RuntimeError(f"item {index + 1}: {error}")
            results.append(final)
    finally:
        context["loop"] = outer
    return {"input": {"count": len(items)}, "output": {"results": results, "count": len(items)}}


async def _run_parallel(node_id, config, context, state: RunState) -> dict[str, Any]:
    graphs = config.get("branches") or []
    outcomes = await asyncio.gather(*(
        _execute_graph(g.get("nodes") or [], g.get("edges") or [], context, state, parent=node_id, label=f"branch {i + 1}")
        for i, g in enumerate(graphs)
    ))
    failed = [f"branch {i + 1}: {error}" for i, (status, error, _) in enumerate(outcomes) if status == "failed"]
    if failed:
        raise RuntimeError("; ".join(failed))
    return {"output": {"branches": [final for _, _, final in outcomes]}}


async def run_node(node: dict[str, Any], context: dict[str, Any], state: RunState) -> dict[str, Any]:
    """Execute one step (with retries and timeout). Raises on failure."""
    node_id = str(node.get("id"))
    node_type = _node_type(node)
    config = _node_config(node)
    retries = max(0, min(int(config.get("retries") or 0), MAX_RETRIES))

    async def once() -> dict[str, Any]:
        if node_type == "action":
            return await _run_action(config, context, state.tool_registry, state.app_connections)
        if node_type == "llm":
            return await _run_llm(config, context, state.workflow_provider_id)
        if node_type == "condition":
            return {"output": {"result": evaluate_condition(config, context)}}
        if node_type == "transform":
            return _run_transform(config, context)
        if node_type == "delay":
            seconds = max(0.0, min(float(config.get("seconds") or 0), MAX_DELAY_SECONDS))
            await asyncio.sleep(seconds)
            return {"output": {"waited_seconds": seconds}}
        if node_type == "http":
            return await _run_http(config, context)
        if node_type == "code":
            return await _run_code(config, context)
        if node_type == "workflow":
            return await _run_subworkflow(config, context, state)
        if node_type == "loop":
            return await _run_loop(node_id, config, context, state)
        if node_type == "parallel":
            return await _run_parallel(node_id, config, context, state)
        if node_type == "output":
            value = render_value(config.get("template"), context) if config.get("template") else context["steps"]
            return {"output": value if isinstance(value, dict) else {"value": value}}
        raise ValueError(f"Unknown step type '{node_type}'")

    containers = ("loop", "parallel", "workflow")
    timeout = config.get("timeout_seconds") or (None if node_type in containers else DEFAULT_STEP_TIMEOUT)
    try:
        result, attempts = await asyncio.wait_for(_with_retries(once, retries), timeout=float(timeout) if timeout else None)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Step timed out after {timeout}s")
    result["attempts"] = attempts + 1
    return result


# ---- graph execution -------------------------------------------------------------

async def _execute_graph(
    nodes, edges, context: dict[str, Any], state: RunState, parent: Optional[str] = None, label: str = "",
) -> tuple[str, Optional[str], dict[str, Any]]:
    order = topological_order(nodes, edges)
    if order is None:
        return "failed", "The workflow contains a cycle", {}
    by_id = {str(node["id"]): node for node in nodes}
    incoming: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in by_id}
    for edge in edges:
        if str(edge.get("target")) in incoming:
            incoming[str(edge["target"])].append(edge)

    outcome: dict[str, str] = {}           # node_id -> success | failed | skipped
    branch: dict[str, bool] = {}           # condition node_id -> result
    status, first_error = "completed", None
    final_output: dict[str, Any] = {}
    last_output: dict[str, Any] = {}
    halted = False

    def edge_active(edge: dict[str, Any]) -> bool:
        source = str(edge.get("source"))
        if outcome.get(source) != "success":
            return False
        if source in branch:
            handle = str(edge.get("sourceHandle") or edge.get("condition") or edge.get("label") or "true").lower()
            return branch[source] == (handle not in ("false", "else", "no"))
        return True

    for node_id in order:
        node = by_id[node_id]
        node_type = _node_type(node)
        config = _node_config(node)
        name = node.get("name") or node_id

        if node_type == "trigger":
            outcome[node_id] = "success"
            context["steps"][node_id] = context.get("trigger")
            continue

        state.counter[0] += 1
        event: dict[str, Any] = {
            "id": f"step-{state.counter[0]}", "nodeId": node_id, "nodeName": f"{name} · {label}" if label else name,
            "type": node_type, "timestamp": _utc_now(), "step": state.counter[0], "status": "success",
        }
        if parent:
            event["parent"] = parent
        state.events.append(event)

        if halted or (incoming[node_id] and not any(edge_active(e) for e in incoming[node_id])):
            outcome[node_id] = event["status"] = "skipped"
            event["type"] = "conditional"
            event["reason"] = "Previous step failed" if halted else "Branch not taken"
            continue

        started = time.perf_counter()
        try:
            if parent is None and node_id in state.reuse:
                result = {"output": state.reuse[node_id], "attempts": 0}
                event["reused"] = True
            else:
                if state.progress:
                    event["status"] = "running"
                    state.progress()
                result = await run_node(node, context, state)
                event["status"] = "success"
            output = result["output"]
            if node_type == "condition":
                branch[node_id] = bool(output.get("result"))
                event["condition"] = branch[node_id]
            if node_type == "action":
                event.update({"type": "tool_executed", "tool": result.get("tool"), "tool_name": result.get("tool"),
                              "app_id": result.get("app_id"), "connected": True})
            if node_type == "output":
                final_output = output
            event["input"] = _sanitize(result.get("input", {}))
            event["output"] = event["data"] = _sanitize(output)
            event["attempts"] = result.get("attempts", 1)
            context["steps"][node_id] = output
            last_output = output
            outcome[node_id] = "success"
        except asyncio.CancelledError:
            event.update({"status": "cancelled", "type": "error", "error": "Run was cancelled"})
            raise
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            event.update({"status": "failed", "type": "error", "error": message})
            if isinstance(exc, PermissionError):
                event["connected"] = False
            first_error = first_error or f"{name}: {message}"
            handler = config.get("on_error")
            handled = False
            if isinstance(handler, dict) and handler.get("nodes"):
                previous_error = context.get("error")
                context["error"] = {"message": message, "step": node_id}
                try:
                    h_status, h_error, _ = await _execute_graph(
                        handler["nodes"], handler.get("edges") or [], context, state, parent=node_id, label="error handler",
                    )
                finally:
                    context["error"] = previous_error
                handled = h_status != "failed"
                if not handled:
                    first_error = f"{name}: error handler failed: {h_error}"
            if handled or config.get("continue_on_error"):
                # Downstream steps still run; they see the error as this step's output.
                outcome[node_id] = "success"
                context["steps"][node_id] = {"error": message}
                status = "partial" if status != "failed" else status
            else:
                outcome[node_id] = "failed"
                status = "failed"
                halted = True
        event["duration"] = int((time.perf_counter() - started) * 1000)
        event["completedAt"] = _utc_now()
        if state.progress:
            state.progress()

    return status, first_error, final_output or last_output


# ---- run entry points ---------------------------------------------------------------

_active_runs: dict[str, asyncio.Task] = {}
_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}


def _run_input(input_data: dict[str, Any], trigger: dict[str, Any]) -> dict[str, Any]:
    return input_data if trigger == {"type": "manual"} else {**input_data, "trigger": trigger}


def _concurrency_limit(row: Any) -> int:
    try:
        raw = json.loads(row["trigger"]) if row["trigger"] and row["trigger"] != "manual" else {}
    except (json.JSONDecodeError, TypeError):
        raw = {}
    return max(0, int(raw.get("concurrency") or 0)) if isinstance(raw, dict) else 0


def _semaphore(workflow_id: int, limit: int) -> Optional[asyncio.Semaphore]:
    if limit <= 0:
        return None
    current = _semaphores.get(workflow_id)
    if current is None or current[0] != limit:
        current = (limit, asyncio.Semaphore(limit))
        _semaphores[workflow_id] = current
    return current[1]


async def run_workflow(workflow_id: int, *args: Any, **kwargs: Any) -> WorkflowRunResult:
    """Run a workflow as its owner: scheduled runs, webhooks and run-once have no signed-in person, and a
    sub-workflow step can only call its owner's own workflows."""
    from app.auth.context import current_user
    from app.auth.owner import as_user

    conn = get_connection()
    try:
        row = conn.execute("SELECT user_id FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Workflow not found")
    owner, acting = row["user_id"], current_user.get()
    if acting is not None and owner is not None and int(acting["id"]) != int(owner):
        raise ValueError("Workflow not found")  # someone else's: as if it didn't exist
    if owner is None or acting is not None:
        return await _run_workflow_as_owner(workflow_id, *args, **kwargs)
    with as_user(int(owner)):
        return await _run_workflow_as_owner(workflow_id, *args, **kwargs)


async def _run_workflow_as_owner(
    workflow_id: int,
    tool_registry: ToolRegistry,
    app_connections: dict[str, bool],
    req: WorkflowRunRequest,
    trigger: Optional[dict[str, Any]] = None,
    run_id: Optional[str] = None,
    depth: int = 0,
    reuse: Optional[dict[str, Any]] = None,
) -> WorkflowRunResult:
    """Run a workflow to completion. Pass ``run_id`` when the run row was already created."""
    started_at = _utc_now()
    input_data = dict(req.input_data or {})
    trigger = trigger or {"type": "manual"}
    run_input = _run_input(input_data, trigger)

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Workflow not found")
    if run_id is None:
        run_id = str(uuid4())
        _insert_run(run_id, workflow_id, started_at, run_input)

    nodes, edges = load_workflow_graph(row)
    state = RunState(tool_registry, app_connections, row["llm_provider_id"], run_id, depth, dict(reuse or {}))
    state.progress = lambda: _update_progress(run_id, state.events)
    status, first_error, final_output = "completed", None, {}

    semaphore = _semaphore(workflow_id, _concurrency_limit(row))
    try:
        if semaphore:
            await semaphore.acquire()
        try:
            if not (row["enabled"] and row["is_active"]):
                status, first_error = "skipped", "Workflow is disabled"
                state.events.append({"id": "workflow-disabled", "nodeId": "workflow", "nodeName": "Workflow", "type": "conditional",
                                     "status": "skipped", "timestamp": started_at, "step": 0, "error": first_error})
            elif not any(_node_type(node) != "trigger" for node in nodes):
                status, first_error = "failed", "Workflow has no steps to run"
            else:
                context = {"input": input_data, "trigger": trigger, "steps": {}}
                status, first_error, final_output = await _execute_graph(nodes, edges, context, state)
        finally:
            if semaphore:
                semaphore.release()
    except asyncio.CancelledError:
        status, first_error = "cancelled", "Run was cancelled"

    completed_at = _utc_now()
    events = state.events
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
            for e in events if e.get("step") and not e.get("parent")
        ]},
        error=first_error,
        events=events,
        trace=events,
        duration_ms=int((datetime.fromisoformat(completed_at[:-1]) - datetime.fromisoformat(started_at[:-1])).total_seconds() * 1000),
    )
    _finish_run(result, [e for e in events if e.get("step")])
    log_activity(
        "workflow_completed" if status in ("completed", "partial") else "workflow_failed",
        f"Workflow '{row['name']}' {status}",
        first_error or f"{sum(1 for e in events if e['status'] == 'success')} step(s) succeeded",
        {"workflow_id": workflow_id, "run_id": run_id, "status": status, "trigger": trigger.get("type")},
    )
    if status == "failed":
        await _alert_failure(row["name"], first_error)
    return result


async def _alert_failure(name: str, error: Optional[str]) -> None:
    """A failed run also reaches the phone (Telegram), unless failure alerts are switched off."""
    from app.api.routes.settings import load_user_settings
    from app.integrations.telegram import notify_all

    if not (load_user_settings().get("notifications") or {}).get("workflowFailure", True):
        return
    try:
        await notify_all(f"Workflow '{name}' failed", error or "")
    except Exception as exc:  # an alert must never break the run's bookkeeping
        logger.warning("Couldn't send the failure alert: %s", exc)


def start_background_run(
    workflow_id: int,
    tool_registry: ToolRegistry,
    app_connections: dict[str, bool],
    req: WorkflowRunRequest,
    trigger: Optional[dict[str, Any]] = None,
    reuse: Optional[dict[str, Any]] = None,
) -> str:
    """Create the run row now and execute in the background; returns the run id."""
    trigger = trigger or {"type": "manual"}
    run_id = str(uuid4())
    _insert_run(run_id, workflow_id, _utc_now(), _run_input(dict(req.input_data or {}), trigger))
    task = asyncio.create_task(run_workflow(
        workflow_id, tool_registry, app_connections, req, trigger=trigger, run_id=run_id, reuse=reuse,
    ))
    _active_runs[run_id] = task
    task.add_done_callback(lambda _: _active_runs.pop(run_id, None))
    return run_id


def cancel_run(run_id: str) -> bool:
    task = _active_runs.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def reusable_outputs(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Outputs of top-level steps that succeeded in an earlier run (for re-run from failure)."""
    return {
        e["nodeId"]: e.get("output", {})
        for e in events
        if e.get("status") == "success" and not e.get("parent") and e.get("step")
    }


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

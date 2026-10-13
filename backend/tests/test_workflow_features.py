"""Section 2 workflow features: loops, parallel, HTTP, code, sub-workflows, error handlers,
timeouts, background runs + cancel, re-run from failure, versions, import/export,
templates, single-step tests and AI drafts."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import app


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # echo the JSON body back with the method
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        self._reply(200, {"method": "POST", "got": json.loads(body or b"{}"), "auth": self.headers.get("authorization")})

    def do_GET(self):
        if self.path == "/fail":
            self._reply(500, {"error": "boom"})
        else:
            self._reply(200, {"method": "GET", "path": self.path})

    def _reply(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def http_base():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def create(client, nodes, edges=None, name="wf", **extra):
    if edges is None:  # chain the nodes in order
        edges = [{"id": f"e{i}", "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]
    r = client.post("/api/workflows", json={"name": name, "isActive": True, "nodes": nodes, "edges": edges, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, wf_id, **body):
    r = client.post(f"/api/workflows/{wf_id}/run", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def by_node(run_result):
    return {e["nodeId"]: e for e in run_result["events"]}


def compose(node_id, template):
    return {"id": node_id, "type": "transform", "name": node_id, "config": {"template": template}}


def body(*nodes):
    return {"nodes": list(nodes), "edges": [{"id": f"b{i}", "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


# ---- loops & parallel ------------------------------------------------------------

def test_loop_runs_body_per_item(client):
    wf = create(client, [
        compose("list", '[1, 2, 3]'),
        {"id": "loop", "type": "loop", "name": "Each", "config": {"items": "{{ steps.list.value }}",
                                                                  "body": body(compose("double", "{{ loop.item * 2 }}"))}},
    ])
    result = run(client, wf["id"])
    assert result["status"] == "completed", result
    out = by_node(result)["loop"]["output"]
    assert out["count"] == 3
    assert [r["value"] for r in out["results"]] == [2, 4, 6]


def test_loop_rejects_non_list(client):
    wf = create(client, [{"id": "loop", "type": "loop", "config": {"items": "not a list", "body": body(compose("x", "1"))}}])
    result = run(client, wf["id"])
    assert result["status"] == "failed" and "list" in result["error"]


def test_parallel_branches_run_concurrently(client):
    wf = create(client, [{"id": "par", "type": "parallel", "name": "Both", "config": {"branches": [
        body({"id": "wait_a", "type": "delay", "config": {"seconds": 1}}, compose("a", "A")),
        body({"id": "wait_b", "type": "delay", "config": {"seconds": 1}}, compose("b", "B")),
    ]}}])
    started = time.perf_counter()
    result = run(client, wf["id"])
    assert result["status"] == "completed", result
    assert time.perf_counter() - started < 1.8  # not 2s sequential
    assert [b["value"] for b in by_node(result)["par"]["output"]["branches"]] == ["A", "B"]


# ---- HTTP & code --------------------------------------------------------------------

def test_http_step(client, http_base):
    wf = create(client, [
        {"id": "call", "type": "http", "config": {"method": "POST", "url": f"{http_base}/hook",
                                                   "headers": {"Authorization": "Bearer x"}, "body": {"n": "{{ input.n }}"}}},
        {"id": "fail", "type": "http", "config": {"method": "GET", "url": f"{http_base}/fail"}},
    ])
    result = run(client, wf["id"], input_data={"n": 7})
    out = by_node(result)["call"]["output"]
    assert out["status"] == 200 and out["data"]["got"] == {"n": 7} and out["data"]["auth"] == "Bearer x"
    assert result["status"] == "failed" and "500" in result["error"]


def test_code_step_sandboxed(client):
    wf = create(client, [
        compose("list", "[3, 4]"),
        {"id": "js", "type": "code", "config": {"code": "return { total: input.steps.list.value.reduce((a, b) => a + b, 0) };"}},
    ])
    assert by_node(run(client, wf["id"]))["js"]["output"]["value"] == {"total": 7}

    for code, needle in (("while (true) {}", "time"), ("return typeof require + typeof fetch;", None)):
        wf = create(client, [{"id": "js", "type": "code", "config": {"code": code}}])
        result = run(client, wf["id"])
        if needle:
            assert result["status"] == "failed" and needle in result["error"].lower()
        else:
            assert by_node(result)["js"]["output"]["value"] == "undefinedundefined"


# ---- sub-workflows & error handling -----------------------------------------------

def test_sub_workflow(client):
    child = create(client, [
        {"id": "t", "type": "trigger", "config": {"trigger_type": "manual", "inputs": [{"name": "who", "type": "text", "required": True}]}},
        compose("greet", "hi {{ trigger.inputs.who }}"),
    ], name="child")
    parent = create(client, [{"id": "sub", "type": "workflow", "config": {"workflow_id": child["id"], "inputs": {"who": "{{ input.name }}"}}}])
    out = by_node(run(client, parent["id"], input_data={"name": "ana"}))["sub"]["output"]
    assert out["status"] == "completed" and out["result"]["value"] == "hi ana"


def test_sub_workflow_recursion_is_stopped(client):
    wf = create(client, [{"id": "self", "type": "workflow", "config": {"workflow_id": 0}}], name="loopy")
    nodes = [{"id": "self", "type": "workflow", "config": {"workflow_id": wf["id"]}}]
    client.patch(f"/api/workflows/{wf['id']}", json={"nodes": nodes, "edges": []})
    result = run(client, wf["id"])
    assert result["status"] == "failed" and "deep" in result["error"].lower()


def test_error_handler_runs_and_flow_continues(client, http_base):
    wf = create(client, [
        {"id": "call", "type": "http", "config": {"method": "GET", "url": f"{http_base}/fail",
                                                   "on_error": body(compose("handled", "caught: {{ error.message }}"))}},
        compose("after", "still ran"),
    ])
    result = run(client, wf["id"])
    nodes = by_node(result)
    assert result["status"] == "partial"
    assert "500" in nodes["handled"]["output"]["value"]
    assert nodes["after"]["output"]["value"] == "still ran"


def test_step_timeout(client):
    wf = create(client, [{"id": "slow", "type": "delay", "config": {"seconds": 3, "timeout_seconds": 1}}])
    result = run(client, wf["id"])
    assert result["status"] == "failed" and "timed out" in result["error"].lower()


def test_validation_covers_nested_steps(client):
    r = client.post("/api/workflows", json={"name": "dup", "nodes": [
        compose("x", "1"),
        {"id": "loop", "type": "loop", "config": {"items": "[]", "body": body(compose("x", "2"))}},
    ], "edges": [{"source": "x", "target": "loop"}]})
    assert r.status_code == 400 and "unique" in r.json()["detail"]


# ---- background runs, cancel, re-run, concurrency -----------------------------------

def _wait(client, wf_id, run_id, done=lambda r: r["status"] != "running", timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/workflows/{wf_id}/runs/{run_id}").json()
        if done(r):
            return r
        time.sleep(0.1)
    raise AssertionError(f"run did not finish: {r}")


def test_background_run_reports_progress_and_cancels(client):
    wf = create(client, [compose("first", "1"), {"id": "wait", "type": "delay", "config": {"seconds": 5}}, compose("last", "2")])
    started = client.post(f"/api/workflows/{wf['id']}/run?background=true", json={}).json()
    assert started["status"] == "running"
    # Progress is visible while running: the first step is done before the delay ends.
    progress = _wait(client, wf["id"], started["id"], done=lambda r: any(e["nodeId"] == "first" for e in r["events"]))
    assert progress["status"] == "running"
    assert client.post(f"/api/workflows/{wf['id']}/runs/{started['id']}/cancel").status_code == 200
    final = _wait(client, wf["id"], started["id"])
    assert final["status"] == "cancelled"
    assert client.post(f"/api/workflows/{wf['id']}/runs/{started['id']}/cancel").status_code == 409


def test_rerun_from_failed_step_reuses_earlier_outputs(client, http_base):
    nodes = [compose("first", "{{ input.n }}"), {"id": "call", "type": "http", "config": {"method": "GET", "url": f"{http_base}/fail"}}, compose("last", "done")]
    wf = create(client, nodes)
    failed = run(client, wf["id"], input_data={"n": 5})
    assert failed["status"] == "failed"
    nodes[1]["config"]["url"] = f"{http_base}/ok"
    client.patch(f"/api/workflows/{wf['id']}", json={"nodes": nodes})
    started = client.post(f"/api/workflows/{wf['id']}/runs/{failed['id']}/rerun").json()
    final = _wait(client, wf["id"], started["id"])
    steps = by_node(final)
    assert final["status"] == "completed", final
    assert steps["first"].get("reused") is True and steps["first"]["output"]["value"] == 5
    assert steps["last"]["output"]["value"] == "done"


def test_concurrency_limit_queues_runs(client):
    wf = create(client, [
        {"id": "t", "type": "trigger", "config": {"trigger_type": "manual", "concurrency": 1}},
        {"id": "wait", "type": "delay", "config": {"seconds": 1}},
    ])
    started = time.perf_counter()
    ids = [client.post(f"/api/workflows/{wf['id']}/run?background=true", json={}).json()["id"] for _ in range(2)]
    for run_id in ids:
        _wait(client, wf["id"], run_id)
    assert time.perf_counter() - started >= 1.9  # second run waited for the first


# ---- versions, import/export, templates -------------------------------------------

def test_versions_and_restore(client):
    wf = create(client, [compose("x", "v1")], name="versioned")
    client.patch(f"/api/workflows/{wf['id']}", json={"nodes": [compose("x", "v2")], "name": "versioned 2"})
    versions = client.get(f"/api/workflows/{wf['id']}/versions").json()
    assert [v["version"] for v in versions] == [1] and versions[0]["name"] == "versioned"
    restored = client.post(f"/api/workflows/{wf['id']}/versions/1/restore").json()
    assert restored["name"] == "versioned" and restored["nodes"][0]["config"]["template"] == "v1"
    assert [v["version"] for v in client.get(f"/api/workflows/{wf['id']}/versions").json()] == [2, 1]


def test_export_import_strips_webhook_secret(client):
    wf = create(client, [{"id": "t", "type": "trigger", "config": {"trigger_type": "webhook"}}, compose("x", "hi")], name="hooked")
    exported = client.get(f"/api/workflows/{wf['id']}/export").json()
    assert exported["format"] == "nexus-workflow/1" and "secret" not in json.dumps(exported)
    imported = client.post("/api/workflows/import", json=exported).json()
    assert imported["name"] == "hooked (imported)" and imported["trigger"] == "webhook"
    assert imported["trigger_config"]["webhook_path"] != wf["trigger_config"]["webhook_path"]
    assert client.post("/api/workflows/import", json={"format": "other"}).status_code == 400


def test_templates(client):
    templates = client.get("/api/workflows/templates").json()
    assert len(templates) >= 3 and all({"id", "name", "description"} <= set(t) for t in templates)
    created = client.post(f"/api/workflows/templates/{templates[0]['id']}").json()
    assert created["name"] == templates[0]["name"] and created["nodes"]


# ---- test one step & AI draft -----------------------------------------------------------

def test_test_step_endpoint(client):
    r = client.post("/api/workflows/test-step", json={
        "node": compose("x", "hello {{ steps.prev.text }} {{ trigger.inputs.who }}"),
        "sample": {"steps": {"prev": {"text": "world"}}, "trigger": {"inputs": {"who": "ana"}}},
    }).json()
    assert r["status"] == "success" and r["output"]["value"] == "hello world ana"
    r = client.post("/api/workflows/test-step", json={"node": {"id": "js", "type": "code", "config": {"code": "throw new Error('nope')"}}}).json()
    assert r["status"] == "failed" and "nope" in r["error"]


class DraftLLM:
    provider_name = "fake"
    default_model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    async def chat(self, messages, **kwargs):
        return {"content": self.replies.pop(0)}


def test_ai_draft(client, monkeypatch):
    import app.workflows.drafting as drafting

    good = {"name": "Digest", "description": "d", "nodes": [
        {"id": "trigger_1", "type": "trigger", "config": {"trigger_type": "recurrence", "frequency": "day", "at": "09:00"}},
        {"id": "llm_1", "type": "llm", "config": {"prompt": "summarize"}},
    ], "edges": [{"source": "trigger_1", "target": "llm_1"}]}
    llm = DraftLLM(["not json at all", "```json\n" + json.dumps(good) + "\n```"])
    monkeypatch.setattr(drafting, "get_default_llm_provider", lambda: (llm, {}))
    r = client.post("/api/workflows/draft", json={"description": "every morning summarize stuff"})
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["name"] == "Digest" and len(draft["nodes"]) == 2 and draft["edges"][0]["target"] == "llm_1"

    monkeypatch.setattr(drafting, "get_default_llm_provider", lambda: (None, None))
    assert client.post("/api/workflows/draft", json={"description": "x"}).status_code == 400


def test_templates_use_the_new_abilities_and_say_what_they_need(client):
    templates = {t["id"]: t for t in client.get("/api/workflows/templates").json()}
    assert {"inbox-triage", "daily-briefing", "daily-reminder", "weekly-report-doc", "web-news"} <= set(templates)
    assert templates["web-news"]["needs"] == ["Web search"] and templates["inbox-triage"]["needs"] == ["Email"]
    assert templates["daily-reminder"]["needs"] == []
    tools = {n["config"].get("tool") for n in client.post("/api/workflows/templates/inbox-triage").json()["nodes"]}
    assert {"nexus__ask_agent", "nexus__notify"} <= tools
    # Every template validates against the real step types and built-in tools.
    for template_id in templates:
        created = client.post(f"/api/workflows/templates/{template_id}")
        assert created.status_code == 200 and not created.json().get("warnings"), (template_id, created.json().get("warnings"))
        client.delete(f"/api/workflows/{created.json()['id']}")

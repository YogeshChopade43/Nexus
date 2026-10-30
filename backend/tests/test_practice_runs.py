"""Practice runs: a workflow runs for real except the steps that would change something, which are listed instead."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class _Handler(BaseHTTPRequestHandler):
    flaky_calls = 0

    def do_POST(self):
        self._reply({"method": "POST"})

    def do_GET(self):
        if self.path == "/flaky":  # fails the first time, works after: for re-run from failure
            _Handler.flaky_calls += 1
            if _Handler.flaky_calls == 1:
                return self._reply({"error": "first time"}, 500)
        self._reply({"method": "GET"})

    def _reply(self, payload, code=200):
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
        r = c.post("/api/mcp/servers", json={"name": "Practice Echo", "transport": "stdio", "command": sys.executable, "args": [FIXTURE]})
        assert r.json()["status"] == "connected", r.json()
        c.server_id = r.json()["id"]
        yield c


def set_policies(client, policies):
    r = client.patch(f"/api/mcp/servers/{client.server_id}", json={"tool_policies": policies})
    assert r.status_code == 200, r.text


def create(client, nodes):
    edges = [{"id": f"e{i}", "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]
    r = client.post("/api/workflows", json={"name": "practice", "isActive": True, "nodes": nodes, "edges": edges})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, wf_id, **body):
    r = client.post(f"/api/workflows/{wf_id}/run", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def by_node(result):
    return {e["nodeId"]: e for e in result["events"]}


def action(node_id, tool, params):
    return {"id": node_id, "type": "action", "name": node_id, "config": {"tool": tool, "parameters": params}}


def compose(node_id, template):
    return {"id": node_id, "type": "transform", "name": node_id, "config": {"template": template}}


def body(*nodes):
    return {"nodes": list(nodes), "edges": [{"id": f"b{i}", "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


def test_practice_run_skips_changing_tools_and_runs_reads(client):
    set_policies(client, {"echo": "ask"})
    wf = create(client, [
        action("write", "practice_echo__echo", {"text": "{{ input.word }}"}),
        action("read", "practice_echo__list_items", {"count": 2}),
        compose("after", "got: {{ steps.write.text }}"),
    ])
    result = run(client, wf["id"], input_data={"word": "mango"}, practice=True)
    steps = by_node(result)
    assert steps["write"]["practice_skipped"] and steps["write"]["would_call"] == "practice_echo__echo"
    assert steps["write"]["input"] == {"text": "mango"}
    assert not steps["read"].get("practice_skipped") and steps["read"]["status"] == "success"
    assert steps["after"]["output"]["value"] == "got: [practice run: practice_echo__echo skipped]"
    assert result["input_data"]["practice"] is True and result["status"] == "completed"
    set_policies(client, {})


def test_normal_run_still_executes_ask_tools(client):
    set_policies(client, {"echo": "ask"})
    result = run(client, create(client, [action("write", "practice_echo__echo", {"text": "hi"})])["id"])
    assert not by_node(result)["write"].get("practice_skipped") and result["status"] == "completed"
    set_policies(client, {})


def test_practice_run_skips_http_post_and_notify_but_runs_get(client, http_base):
    wf = create(client, [
        {"id": "post", "type": "http", "name": "post", "config": {"method": "POST", "url": f"{http_base}/hook"}},
        {"id": "get", "type": "http", "name": "get", "config": {"method": "GET", "url": f"{http_base}/x"}},
        action("ping", "nexus__notify", {"title": "t", "message": "m"}),
    ])
    steps = by_node(run(client, wf["id"], practice=True))
    assert steps["post"]["practice_skipped"] and steps["post"]["would_call"] == f"HTTP POST {http_base}/hook"
    assert steps["get"]["output"]["status"] == 200
    assert steps["ping"]["practice_skipped"]


def test_practice_run_skips_inside_loops(client):
    set_policies(client, {"echo": "ask"})
    wf = create(client, [
        compose("list", '["a", "b"]'),
        {"id": "loop", "type": "loop", "name": "Each", "config": {"items": "{{ steps.list.value }}",
         "body": body(action("say", "practice_echo__echo", {"text": "{{ loop.item }}"}))}},
    ])
    result = run(client, wf["id"], practice=True)
    echoes = [e for e in result["events"] if e.get("nodeId") == "say"]
    assert len(echoes) == 2 and all(e.get("practice_skipped") for e in echoes), result
    set_policies(client, {})


def test_condition_on_skipped_step_is_uncertain(client):
    set_policies(client, {"echo": "ask"})
    wf = create(client, [
        action("write", "practice_echo__echo", {"text": "hi"}),
        {"id": "check", "type": "condition", "name": "check", "config": {"field": "steps.write.data.ok", "operator": "truthy"}},
    ])
    assert by_node(run(client, wf["id"], practice=True))["check"]["uncertain"] is True
    set_policies(client, {})


def wait_for(client, wf_id, run_id):
    for _ in range(200):
        run_ = client.get(f"/api/workflows/{wf_id}/runs/{run_id}").json()
        if run_["status"] not in ("running", "queued"):
            return run_
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_background_practice_run_is_stored_as_practice(client):
    set_policies(client, {"echo": "ask"})
    wf = create(client, [action("write", "practice_echo__echo", {"text": "hi"})])
    r = client.post(f"/api/workflows/{wf['id']}/run", params={"background": "true"}, json={"practice": True})
    run_ = wait_for(client, wf["id"], r.json()["id"])
    assert run_["input_data"]["practice"] is True
    assert by_node(run_)["write"]["practice_skipped"]
    set_policies(client, {})


def test_rerun_of_a_practice_run_stays_a_practice_run(client, http_base):
    set_policies(client, {"echo": "ask"})
    _Handler.flaky_calls = 0
    wf = create(client, [
        {"id": "fetch", "type": "http", "name": "fetch", "config": {"method": "GET", "url": f"{http_base}/flaky"}},
        action("write", "practice_echo__echo", {"text": "hi"}),
    ])
    first = run(client, wf["id"], practice=True)
    assert first["status"] == "failed"
    rerun = client.post(f"/api/workflows/{wf['id']}/runs/{first['id']}/rerun").json()
    again = wait_for(client, wf["id"], rerun["id"])
    assert again["input_data"]["practice"] is True and by_node(again)["write"]["practice_skipped"]
    set_policies(client, {})


def test_resumed_practice_run_stays_a_practice_run(client):
    from app.workflows import engine
    from app.mcp import server_availability
    from app.tools import get_tool_registry

    set_policies(client, {"echo": "ask"})
    wf = create(client, [action("write", "practice_echo__echo", {"text": "hi"})])
    interrupted = {"id": "gone", "workflow_id": wf["id"], "input_data": json.dumps({"practice": True}), "events": "[]"}
    client.portal.call(engine.resume_interrupted_runs, [interrupted], get_tool_registry(), server_availability)
    runs = client.get(f"/api/workflows/{wf['id']}/runs").json()
    latest = runs[0] if isinstance(runs, list) else runs["runs"][0]
    run_ = wait_for(client, wf["id"], latest["id"])
    assert run_["input_data"]["practice"] is True and by_node(run_)["write"]["practice_skipped"]
    set_policies(client, {})


def test_practice_run_skips_app_and_action_configs(client):
    set_policies(client, {"echo": "ask"})
    wf = create(client, [{"id": "write", "type": "action", "name": "write",
                          "config": {"app": "practice_echo", "action": "_echo", "parameters": {"text": "hi"}}}])
    assert by_node(run(client, wf["id"], practice=True))["write"]["practice_skipped"]
    set_policies(client, {})


def test_practice_run_skips_write_tools_even_when_allowed(client):
    wf = create(client, [action("save", "nexus__remember", {"fact": "practice runs change nothing"})])
    steps = by_node(run(client, wf["id"], practice=True))
    assert steps["save"]["practice_skipped"] and steps["save"]["would_call"] == "nexus__remember"


def test_practice_summary_includes_sub_workflow_changes(client):
    set_policies(client, {"echo": "ask"})
    child = create(client, [action("write", "practice_echo__echo", {"text": "hi"})])
    parent = create(client, [{"id": "sub", "type": "workflow", "name": "sub", "config": {"workflow_id": child["id"]}}])
    result = run(client, parent["id"], practice=True)
    skipped = [e for e in result["events"] if e.get("practice_skipped")]
    assert [e["would_call"] for e in skipped] == ["practice_echo__echo"] and skipped[0]["parent"] == "sub"
    set_policies(client, {})

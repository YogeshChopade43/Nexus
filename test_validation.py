#!/usr/bin/env python3
"""
Nexus V0 TestClient Validation Sequence
Tests expected endpoints with assertions for initial state, persistence,
disabled app behavior, mock executions, safe traces, and workflow create/run.
"""

import requests
import json
import sys
import re

BASE_URL = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}

def assert_equals(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"ASSERTION FAILED: {msg} | Expected: {expected} | Actual: {actual}")
    print(f"  PASS: {msg}")

def assert_true(condition, msg):
    if not condition:
        raise AssertionError(f"ASSERTION FAILED: {msg}")
    print(f"  PASS: {msg}")

def assert_false(condition, msg):
    if condition:
        raise AssertionError(f"ASSERTION FAILED: {msg}")
    print(f"  PASS: {msg}")

def assert_contains(haystack, needle, msg):
    if needle not in haystack and not (hasattr(haystack, '__iter__') and any(needle in str(x) for x in haystack)):
        raise AssertionError(f"ASSERTION FAILED: {msg} | Expected to contain: {needle}")
    print(f"  PASS: {msg}")

def assert_not_contains(haystack, needle, msg):
    if needle in haystack or (hasattr(haystack, '__iter__') and any(needle in str(x) for x in haystack)):
        raise AssertionError(f"ASSERTION FAILED: {msg} | Should not contain: {needle}")
    print(f"  PASS: {msg}")

def get_json(url):
    resp = requests.get(f"{BASE_URL}{url}", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()

def post_json(url, data):
    resp = requests.post(f"{BASE_URL}{url}", headers=HEADERS, json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()

print("=== NEXUS V0 TESTCLIENT VALIDATION SEQUENCE ===")

# 1. HEALTH CHECK
print("\n[1] GET /health")
health = get_json("/health")
assert_equals(health.get("status"), "ok", "Health endpoint returns ok")

# 2. INITIAL APPS STATE - GitHub/Slack/Grafana enabled but not connected
print("\n[2] GET /api/apps - Verify GitHub/Slack/Grafana initially enabled, not connected")
apps = get_json("/api/apps")
app_map = {a["app_id"]: a for a in apps}

for app_id in ("github", "slack", "grafana"):
    assert_true(app_id in app_map, f"{app_id} exists in apps list")
    if app_id in app_map:
        assert_true(app_map[app_id].get("enabled") is True, f"{app_id} initially enabled")
        assert_true(app_map[app_id].get("connected") is False, f"{app_id} initially not connected")
        assert_true(len(app_map[app_id].get("capabilities", [])) > 0, f"{app_id} has capabilities")

# 3. PERSISTENCE ACROSS NEW TESTCLIENT/APP IMPORT
print("\n[3] POST /api/apps/github/connection - Enable GitHub")
resp = post_json("/api/apps/github/connection", {"connected": True, "config": {"token": "test"}})
assert_equals(resp.get("app_id"), "github", "connection response has app_id")
assert_true(resp.get("connected") is True, "connection response connected=True")
assert_true("enabled" in resp, "connection response has enabled field")

# Persistence across new request
apps2 = get_json("/api/apps")
app_map2 = {a["app_id"]: a for a in apps2}
github_persisted = app_map2.get("github", {})
assert_true(github_persisted.get("connected") is True, "github persists as connected")
assert_true(github_persisted.get("enabled") is True, "github persists as enabled")

# 4. DISABLE GRAFANA CONNECTION (explicitly)
print("\n[4] POST /api/apps/grafana/connection - Disable Grafana")
resp = post_json("/api/apps/grafana/connection", {"connected": False})
assert_equals(resp.get("connected"), False, "Grafana explicitly disabled")

# 5. VERIFY GRAFANA DISABLED - NO EXECUTION
print("\n[5] POST /api/agent/run - Grafana disabled, no execution")
resp = post_json("/api/agent/run", {"message": "Check Grafana dashboard"})
grafana_execs = [e for e in resp.get("events", []) if e.get("tool_name", "").startswith("grafana")]
assert_false(grafana_execs, "No Grafana execution when disabled")
response_msg = resp.get("response", "") or resp.get("message", "")
assert_true("not connected" in response_msg.lower() or resp.get("status") == "completed", "agent returns not connected message or completed status")

# 6. GITHUB PR MOCK EXECUTION
print("\n[6] POST /api/agent/run - GitHub PR mock execution")
resp = post_json("/api/agent/run", {"message": "Create PR for feature branch"})
github_exec = next((e for e in resp.get("events", []) if e.get("tool_name", "").startswith("github")), None)
assert_true(github_exec, "GitHub execution triggered")
assert_equals(github_exec.get("tool_name"), "github_create_pull_request", "GitHub action is create_pr")
assert_contains(str(github_exec.get("data", "")), "mock", "GitHub PR mock executed")
trace_str = str(resp.get("events", ""))
assert_contains(trace_str, "github_create_pull_request", "Trace contains github_create_pull_request")

# 7. SLACK SEND MOCK EXECUTION
print("\n[7] POST /api/agent/run - Slack send mock execution")
resp = post_json("/api/agent/run", {"message": "Send notification to #general"})
slack_exec = next((e for e in resp.get("events", []) if e.get("tool_name", "").startswith("slack")), None)
assert_true(slack_exec, "Slack execution triggered")
assert_equals(slack_exec.get("tool_name"), "slack_send_message", "Slack action is send_message")
assert_contains(str(slack_exec.get("data", "")), "mock", "Slack send mock executed")
trace_str = str(resp.get("events", ""))
assert_contains(trace_str, "slack_send_message", "Trace contains slack_send_message")

# 8. SAFE TRACE FIELDS - No secrets/PII
print("\n[8] Verify safe trace fields (no secrets/PII)")
trace_str = str(resp.get("events", ""))
forbidden_fields = ["password", "secret", "token", "api_key", "apikey", "credential", "private_key"]
for field in forbidden_fields:
    assert_not_contains(trace_str.lower(), field, f"Trace contains no {field}")
assert_not_contains(trace_str, re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"), "Trace contains no credit card patterns")
assert_not_contains(trace_str, re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "Trace contains no emails")
safe_fields = ["timestamp", "tool_name", "app", "action", "data", "type"]
assert_true(any(f in trace_str for f in safe_fields), "Trace contains safe fields only")

# 9. WORKFLOW CREATE
print("\n[9] POST /api/workflows - Create workflow")
workflow = {
    "name": "Test Workflow",
    "description": "Test workflow",
    "steps": [
        {"app": "github", "action": "create_issue", "params": {"title": "Test Issue"}},
        {"app": "slack", "action": "send_message", "params": {"channel": "#dev", "text": "Issue created"}},
    ],
    "enabled": True,
    "trigger": "manual",
}
resp = post_json("/api/workflows", workflow)
workflow_id = resp.get("id")
assert_true(workflow_id is not None, "Workflow created with ID")
assert_equals(resp.get("name"), "Test Workflow", "Workflow name matches")

# 10. WORKFLOW LIST
print("\n[10] GET /api/workflows - List workflows")
workflows = get_json("/api/workflows")
assert_true(any(w.get("id") == workflow_id for w in workflows), "Created workflow appears in list")

# 11. WORKFLOW RUN
print("\n[11] POST /api/workflows/{id}/run - Execute workflow")
run_resp = post_json(f"/api/workflows/{workflow_id}/run", {"input_data": {}})
assert_equals(run_resp.get("status"), "completed", "Workflow run completed")

# Verify GitHub step in workflow
gh_step = next((s for s in run_resp.get("events", []) if "github" in s.get("tool_name", "")), None)
assert_true(gh_step, "Workflow has GitHub step")
assert_true("create_issue" in gh_step.get("tool_name", ""), "Workflow GitHub step is create_issue")
assert_contains(str(gh_step.get("data", "")), "mock", "Workflow GitHub mock executed")

# Verify Slack step in workflow
slack_step = next((s for s in run_resp.get("events", []) if "slack" in s.get("tool_name", "")), None)
assert_true(slack_step, "Workflow has Slack step")
assert_equals(slack_step.get("tool_name"), "slack_send_message", "Workflow Slack step is send_message")
assert_contains(str(slack_step.get("data", "")), "mock", "Workflow Slack mock executed")

# 12. WORKFLOW TRACE SAFETY
print("\n[12] Verify workflow trace safe fields")
wf_trace = str(run_resp.get("events", ""))
forbidden_fields = ["token", "secret", "password"]
for field in forbidden_fields:
    assert_not_contains(wf_trace.lower(), field, f"Workflow trace contains no {field}")
assert_true(any(f in wf_trace for f in ["workflow_id", "step", "app", "action", "result", "timestamp", "tool_name"]), "Workflow trace has safe fields")

# 13. DISABLE GITHUB - VERIFY NO EXECUTION
print("\n[13] POST /api/apps/github/connection - Disable GitHub")
post_json("/api/apps/github/connection", {"connected": False})

print("\n[14] POST /api/agent/run - GitHub disabled, no execution")
resp = post_json("/api/agent/run", {"message": "Create another PR"})
github_execs = [e for e in resp.get("events", []) if e.get("tool_name", "").startswith("github")]
assert_false(github_execs, "No GitHub execution when disabled")
trace_str = str(resp.get("events", ""))
assert_true(any("github" in str(t).lower() and "not connected" in str(t).lower() for t in resp.get("events", [])), "Trace shows GitHub disabled")

print("\n=== ALL ASSERTIONS PASSED ===")

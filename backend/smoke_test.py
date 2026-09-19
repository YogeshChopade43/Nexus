import os
import ast
import sys
import tempfile
from typing import Any

os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "nexus_test.db")
os.environ["NEXUS_SKIP_VALIDATION"] = "true"

sys.path.insert(0, "D:\\Tech\\Nexus\\backend")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
results = []

# 1. Health check
r = client.get("/health")
results.append(("GET /health", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["status"] == "ok"

# 2. List apps - all should appear (enabled=True), connection defaults false
r = client.get("/api/apps")
results.append(("GET /api/apps", r.status_code, r.json()))
assert r.status_code == 200
apps = r.json()
app_ids = [a["app_id"] for a in apps]
assert "github" in app_ids
assert "slack" in app_ids
assert "grafana" in app_ids
assert "notion" in app_ids
for a in apps:
    assert "capabilities" in a, f"Missing capabilities for {a['app_id']}"
    assert isinstance(a["capabilities"], list)
for a in apps:
    if a["app_id"] in ("github", "slack", "grafana"):
        assert a["enabled"] is True, f"{a['app_id']} should be enabled"
        assert a["connected"] is False, f"{a['app_id']} should not be connected"
        assert len(a["capabilities"]) > 0, f"{a['app_id']} should have capabilities"
notion = [a for a in apps if a["app_id"] == "notion"][0]
assert notion["enabled"] is True

# 3. Get specific app
r = client.get("/api/apps/github")
results.append(("GET /api/apps/github", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["app_id"] == "github"
assert "capabilities" in r.json()

# 4. Connect GitHub via connection endpoint
r = client.post("/api/apps/github/connection", json={"connected": True, "config": {"token": "test"}})
results.append(("POST /api/apps/github/connection", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["connected"] is True
assert r.json()["app_id"] == "github"
assert "enabled" in r.json()

# 5. Connect Slack
r = client.post("/api/apps/slack/connection", json={"connected": True})
assert r.status_code == 200
assert r.json()["connected"] is True

# Disconnect GitHub so agent returns "not connected"
r = client.post("/api/apps/github/connection", json={"connected": False})
assert r.status_code == 200
assert r.json()["connected"] is False

# 6. Agent: GitHub request returns "not connected" since no config
r = client.post("/api/agent/run", json={"message": "Show me open pull requests on GitHub"})
results.append(("POST /api/agent/run", r.status_code, r.json()))
assert r.status_code == 200
resp = r.json()
assert "not connected" in (resp.get("response", "") + resp.get("message", "")).lower()

# 7. Create workflow
r = client.post("/api/workflows", json={
    "name": "Test WF",
    "description": "test",
    "steps": [{"app": "github", "action": "list_pull_requests"}],
    "enabled": True,
    "trigger": "manual",
})
results.append(("POST /api/workflows", r.status_code, r.json()))
assert r.status_code == 200
wf = r.json()
wf_id = wf["id"]
assert wf["enabled"] is True

# 8. List workflows
r = client.get("/api/workflows")
results.append(("GET /api/workflows", r.status_code, r.json()))
assert r.status_code == 200
assert len(r.json()) >= 1

# 9. Run workflow - steps skipped since no connection
r = client.post(f"/api/workflows/{wf_id}/run", json={"input_data": {}})
results.append(("POST /api/workflows/{id}/run", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["status"] in ("completed", "partial", "skipped")

# 10. Tools endpoints
r = client.get("/api/tools/")
results.append(("GET /api/tools/", r.status_code, r.json()))
assert r.status_code == 200

r = client.get("/api/tools/app/github")
results.append(("GET /api/tools/app/github", r.status_code, r.json()))
assert r.status_code == 200

r = client.get("/api/tools/app/grafana")
results.append(("GET /api/tools/app/grafana", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["connected"] is False
assert r.json()["tools"] == []

# 11. Workflow runs endpoint
r = client.get(f"/api/workflows/{wf_id}/runs")
results.append(("GET /api/workflows/{id}/runs", r.status_code, r.json()))
assert r.status_code == 200
assert "workflow_id" in r.json()
assert "last_run" in r.json()

# 12. Workflow trace endpoint
r = client.get(f"/api/workflows/{wf_id}/trace")
results.append(("GET /api/workflows/{id}/trace", r.status_code, r.json()))
assert r.status_code == 200
assert "workflow_id" in r.json()
assert "steps" in r.json()

# 13. Python 3.9 compatibility check
for root, dirs, files in os.walk("D:\\Tech\\Nexus\\backend"):
    dirs[:] = [d for d in dirs if d not in (".venv", "__pycache__", "node_modules")]
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                    assert False, f"BitOr operator found in {path} at line {node.lineno}"

print("\n=== SMOKE TEST RESULTS ===")
for name, status, data in results:
    print(f"  {name}: {status} OK")
print(f"\nAll {len(results)} tests passed!")

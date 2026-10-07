import os
import ast
import sys
import tempfile
from typing import Any

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(prefix="nexus-smoke-"), "nexus.db")
os.environ["NEXUS_SECRET_KEY"] = "test-secret-key-for-smoke-tests"

sys.path.insert(0, "D:\\Tech\\Nexus\\backend")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
client.__enter__()  # run the app lifespan (database init, seeding, scheduler)
results = []

# 1. Health check
r = client.get("/health")
results.append(("GET /health", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["status"] == "ok"

# 2. MCP servers start empty; tools come only from connected servers
r = client.get("/api/mcp/servers")
results.append(("GET /api/mcp/servers", r.status_code, r.json()))
assert r.status_code == 200 and r.json() == []

# 6. Agent without an LLM provider explains what is missing
r = client.post("/api/agent/run", json={"message": "hello"})
results.append(("POST /api/agent/run", r.status_code, r.json()))
assert r.status_code == 200
assert "no llm provider" in r.json()["response"].lower()

# 7. Create workflow
r = client.post("/api/workflows", json={
    "name": "Test WF",
    "description": "test",
    "steps": [{"tool": "github__list_pull_requests"}],
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
assert r.json()["status"] == "failed"  # no MCP server provides that tool
assert "not found" in r.json()["error"].lower()

# 10. Tools endpoints
r = client.get("/api/tools/")
results.append(("GET /api/tools/", r.status_code, r.json()))
assert r.status_code == 200

r = client.get("/api/tools/app/github")
results.append(("GET /api/tools/app/github", r.status_code, r.json()))
assert r.status_code == 200
assert r.json()["connected"] is False and r.json()["tools"] == []

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

print("\n=== SMOKE TEST RESULTS ===")
for name, status, data in results:
    print(f"  {name}: {status} OK")
print(f"\nAll {len(results)} tests passed!")

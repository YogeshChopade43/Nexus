from __future__ import annotations
import sys
import tempfile
import os

# Use isolated database for testing
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "nexus_test_empty.db")

sys.path.insert(0, "D:\\Tech\\Nexus\\backend")
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Test 1: GET /api/apps on fresh DB - all apps should appear
r = client.get("/api/apps")
print(f"GET /api/apps: {r.status_code}")
assert r.status_code == 200
apps = r.json()
print(f"  Found {len(apps)} apps")
for a in apps:
    print(f"  {a['app_id']}: enabled={a['enabled']}, connected={a['connected']}, capabilities={a['capabilities']}")

# Verify all expected apps appear
app_ids = [a["app_id"] for a in apps]
assert "github" in app_ids, "GitHub missing"
assert "slack" in app_ids, "Slack missing"
assert "grafana" in app_ids, "Grafana missing"
assert "jira" in app_ids, "Jira missing"
assert "linear" in app_ids, "Linear missing"
assert "notion" in app_ids, "Notion missing"

# All should have connected=False initially
for a in apps:
    assert a["connected"] is False, f"{a['app_id']} should have connected=False, got {a['connected']}"

# GitHub/Slack/Grafana should be enabled but not connected
for a in apps:
    if a["app_id"] in ("github", "slack", "grafana"):
        assert a["enabled"] is True, f"{a['app_id']} should be enabled"
        assert a["connected"] is False, f"{a['app_id']} should not be connected"
        assert len(a["capabilities"]) > 0, f"{a['app_id']} should have capabilities"

# Notion should be enabled (definition availability), connected=False
notion = [a for a in apps if a["app_id"] == "notion"][0]
assert notion["enabled"] is True
assert notion["connected"] is False

# Verify individual app
r = client.get("/api/apps/github")
print(f"GET /api/apps/github: {r.status_code}")
assert r.status_code == 200
app = r.json()
assert app["app_id"] == "github"
assert app["enabled"] is True
assert app["connected"] is False

print("\nAll empty-DB tests passed!")

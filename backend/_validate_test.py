import os
import sys
import tempfile
import uuid

db_path = os.path.join(tempfile.gettempdir(), f"nexus_validate_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_PATH"] = db_path
sys.path.insert(0, "D:\\Tech\\Nexus\\backend")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name} {detail}")
    results.append((name, condition))

# 1. Health check
r = client.get("/health")
check("GET /health", r.status_code == 200 and r.json()["status"] == "ok")

# 2. Connect GitHub with valid credentials format (token present) but API will fail
# This should return 400 because validation fails
r = client.post("/api/apps/github/connection", json={"connected": True, "config": {"token": "test"}})
print(f"\nGitHub connect with test token: {r.status_code}")
print(f"  Response: {r.json()}")
# Since there's no real GitHub API, validation will fail with an HTTP error
# The important thing is that the connection is NOT stored
check("GitHub connect - rejects bad credentials", r.status_code == 400, f"got {r.status_code}")

# 3. Verify connection is NOT stored
r = client.get("/api/apps/github")
print(f"\nGitHub app after failed connect: {r.json()}")
check("GitHub not stored as connected", r.json().get("connected") is False)

# 4. Connect with empty config - should fail config validation
r = client.post("/api/apps/github/connection", json={"connected": True, "config": {}})
print(f"\nGitHub connect with empty config: {r.status_code}")
check("GitHub connect - rejects empty config", r.status_code == 400)

# 5. Disconnect without validation
r = client.post("/api/apps/github/connection", json={"connected": False})
check("GitHub disconnect works", r.status_code == 200 and r.json().get("connected") is False)

# 6. Connect Slack with valid format
r = client.post("/api/apps/slack/connection", json={"connected": True, "config": {"bot_token": "test"}})
print(f"\nSlack connect with test token: {r.status_code}")
check("Slack connect - rejects bad credentials", r.status_code == 400)

# 7. Connect without connected flag but with config - should still validate
r = client.post("/api/apps/github/connection", json={"config": {"token": "test"}, "enabled": True})
print(f"\nGitHub connect via enabled: {r.status_code}")
check("GitHub connect via enabled - validates", r.status_code == 400)

print(f"\n=== {sum(1 for _, ok in results if ok)}/{len(results)} PASSED ===")

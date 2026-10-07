"""Shared test environment: must be set before any test module imports the app."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="nexus-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "nexus.db")
os.environ["NEXUS_SECRET_KEY"] = "test-secret"
os.environ["RATE_LIMIT"] = "10000/minute"
os.environ["NEXUS_ALLOW_REMOTE_STDIO"] = "true"  # TestClient's host is not localhost

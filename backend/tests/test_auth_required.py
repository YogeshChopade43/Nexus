"""Everything under /api needs a signed-in person, except signing in itself and callbacks with their own checks."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def signed_out():
    with TestClient(app, auto_login=False) as c:
        yield c


@pytest.fixture(scope="module")
def signed_in():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("method,path", [
    ("get", "/api/workflows/"),
    ("get", "/api/settings/"),
    ("post", "/api/agent/run/stream"),  # streamed chat replies too
    ("get", "/api/files/0123456789abcdef/x.png"),  # file downloads and <img> previews too
    ("get", "/api/run-once"),
])
def test_api_needs_a_session(signed_out, method, path):
    response = getattr(signed_out, method)(path)
    assert response.status_code == 401 and response.json() == {"detail": "Sign in to use Nexus"}


def test_signing_in_and_callbacks_stay_open(signed_out):
    assert signed_out.get("/health/").status_code == 200
    assert signed_out.get("/api/auth/status").status_code == 200
    assert signed_out.post("/api/webhooks/workflows/1", params={"token": "x"}).status_code in (403, 404)  # its own check


def test_a_made_up_session_is_refused(signed_out):
    signed_out.cookies.set("nexus_session", "made-up-token")
    try:
        assert signed_out.get("/api/workflows/").status_code == 401
    finally:
        signed_out.cookies.clear()


def test_with_a_session_everything_works(signed_in):
    assert signed_in.get("/api/workflows/").status_code == 200
    assert signed_in.get("/api/auth/me").json()["email"] == "tester@example.com"

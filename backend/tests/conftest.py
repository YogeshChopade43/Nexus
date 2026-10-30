"""Shared test environment: must be set before any test module imports the app."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="nexus-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "nexus.db")
os.environ["NEXUS_SECRET_KEY"] = "test-secret"
os.environ["RATE_LIMIT"] = "10000/minute"
os.environ["NEXUS_ALLOW_REMOTE_STDIO"] = "true"  # TestClient's host is not localhost
os.environ["NEXUS_ALLOW_LOCAL_SERVERS"] = "true"  # fixture MCP servers are local programs (app: hosted only)
os.environ["NEXUS_RAG_EMBEDDER"] = "fake"  # tests never download models (see app/rag/embeddings.py)
os.environ["NEXUS_RAG_RERANKER"] = "fake"
os.environ["NEXUS_REGISTRY_SYNC"] = "off"  # no background MCP Registry syncs (tests sync a fake on demand)
os.environ["NEXUS_ALLOWED_HOSTS"] = "testserver"  # TestClient sends Host: testserver (the app accepts localhost only)

if os.getenv("NEXUS_TEST_POSTGRES") == "1":  # the same suite on PostgreSQL: a private throwaway server (pip install pgserver)
    import logging

    import pgserver

    logging.getLogger("pgserver").setLevel(logging.WARNING)  # its shutdown logs after pytest closed the output

    _server = pgserver.get_server(os.path.join(_tmp, "pg"), cleanup_mode="stop")
    _server.psql("CREATE DATABASE nexus_test;")
    os.environ["DATABASE_URL"] = _server.get_uri("nexus_test")


# Signed in by default: TestClient(app) signs in a shared test account on entering (creating it if needed), so every
# test module talks to the API like a logged-in person. TestClient(app, auto_login=False) stays signed out.
import fastapi.testclient as _testclient  # noqa: E402

TEST_EMAIL = "tester@example.com"


def _test_account(email: str = TEST_EMAIL) -> dict:
    """The shared test account is the install's admin (as whoever runs a Nexus is); other emails are regular users."""
    from app.auth import store
    from app.core.database import get_connection

    user = store._row("email = ?", email) or store.create_user(email, "test password 123", email.split("@")[0])
    if email == TEST_EMAIL and not user["is_admin"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))
            conn.commit()
        finally:
            conn.close()
        user = store._row("email = ?", email)
    return user


class _SignedInClient(_testclient.TestClient):
    def __init__(self, *args, auto_login: bool = True, user: str = TEST_EMAIL, **kwargs):
        super().__init__(*args, **kwargs)
        self._auto_login = auto_login
        self._user = user  # another email signs in as someone else (isolation tests)

    def __enter__(self):
        client = super().__enter__()
        if self._auto_login:
            from app.auth import store

            user = _test_account(self._user)
            client.cookies.set("nexus_session", store.create_session(user["id"]))
        return client


_testclient.TestClient = _SignedInClient


# Test code acts as the test account too (as the app's own code does inside a signed-in request or a job run as its
# owner): direct calls into stores, tools and settings belong to the same person as the signed-in test client.
# Tests about having no one to act for clear it themselves (current_user.set(None)).
import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: checks SQLite internals (files, PRAGMAs, FTS5, the migration chain)")


def pytest_collection_modifyitems(items):
    if os.getenv("DATABASE_URL"):
        for item in items:
            if item.get_closest_marker("sqlite_only"):
                item.add_marker(pytest.mark.skip(reason="SQLite only"))


@pytest.fixture()
def account():
    """account(email) -> that person's user row, created if needed (import this fixture, never this module)."""
    return _test_account


@pytest.fixture(autouse=True)
def _act_as_test_account():
    from app.api.routes import auth
    from app.auth import store
    from app.auth.context import current_user
    from app.core.database import init_db

    init_db()
    auth.reset_rate_limits()  # per-IP limits are process-global; don't let one test's attempts spill into the next
    user = _test_account()
    token = current_user.set(user)
    yield
    current_user.reset(token)

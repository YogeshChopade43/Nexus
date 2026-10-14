"""Running a published Nexus: the admin's users, instance settings, deployment checklist and the storage quota."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from app.main import app

MEMBER = "member@example.com"


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def member(account):
    account(MEMBER)
    with TestClient(app, user=MEMBER) as c:
        yield c


@pytest.fixture(autouse=True)
def _defaults(admin):
    yield
    admin.patch("/api/admin/instance", json={"signups": None, "storageLimitMb": 1024})
    member_row = store._row("email = ?", MEMBER)
    if member_row:
        admin.patch(f"/api/admin/users/{member_row['id']}", json={"disabled": False, "isAdmin": False})


def test_only_admins_reach_the_admin_api(member):
    for path in ("/api/admin/users", "/api/admin/instance", "/api/admin/deployment"):
        assert member.get(path).status_code == 403


def test_the_admin_sees_every_user_with_their_usage(admin, member):
    users = {u["email"]: u for u in admin.get("/api/admin/users").json()}
    assert {"tester@example.com", MEMBER} <= users.keys()
    row = users[MEMBER]
    assert row["isAdmin"] is False and row["disabled"] is False
    assert {"tokens30d", "storageBytes", "createdAt"} <= row.keys()
    assert "password_hash" not in row


def test_disabling_someone_signs_them_out_everywhere(admin, member):
    user = store._row("email = ?", MEMBER)
    assert member.get("/api/auth/me").status_code == 200
    assert admin.patch(f"/api/admin/users/{user['id']}", json={"disabled": True}).json()["disabled"] is True
    assert member.get("/api/auth/me").status_code == 401
    assert store.authenticate(MEMBER, "test password 123") is None  # and can't sign back in
    admin.patch(f"/api/admin/users/{user['id']}", json={"disabled": False})
    assert store.authenticate(MEMBER, "test password 123") is not None


def test_admins_can_promote_but_never_lock_themselves_out(admin, member):
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"isAdmin": False}).status_code == 409
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"disabled": True}).status_code == 409
    user = store._row("email = ?", MEMBER)
    assert admin.patch(f"/api/admin/users/{user['id']}", json={"isAdmin": True}).json()["isAdmin"] is True
    assert admin.patch("/api/admin/users/999999", json={"disabled": True}).status_code == 404


def test_signups_follow_the_admin_s_switch(admin):
    signed_out = TestClient(app, auto_login=False)
    admin.patch("/api/admin/instance", json={"signups": "open"})
    assert signed_out.get("/api/auth/status").json()["signupsOpen"] is True
    admin.patch("/api/admin/instance", json={"signups": "closed"})
    assert signed_out.get("/api/auth/status").json()["signupsOpen"] is False
    assert admin.patch("/api/admin/instance", json={"signups": "maybe"}).status_code == 422


def test_the_deployment_checklist_names_what_to_fix(admin):
    checks = {c["id"]: c for c in admin.get("/api/admin/deployment").json()}
    assert {"secret_key", "database", "https", "allowed_hosts", "email", "google", "signups"} <= checks.keys()
    assert checks["database"]["ok"] in (True, False) and checks["database"]["detail"]
    assert checks["https"]["ok"] is False  # tests run on plain http without NEXUS_PUBLIC_URL


def test_storage_quota_stops_uploads_past_the_limit(admin, member):
    admin.patch("/api/admin/instance", json={"storageLimitMb": 1})
    small = member.post("/api/files", files={"file": ("a.txt", b"x" * 1000, "text/plain")})
    assert small.status_code == 200
    big = member.post("/api/files", files={"file": ("b.txt", b"x" * 1_100_000, "text/plain")})
    assert big.status_code == 413 and "1 MB" in big.json()["detail"]
    library = member.post("/api/rag/collections", json={"name": "quota"}).json()
    refused = member.post(f"/api/rag/collections/{library['id']}/documents",
                          files={"file": ("big.txt", b"word " * 220_000, "text/plain")})
    assert refused.status_code == 413
    used = {u["email"]: u for u in admin.get("/api/admin/users").json()}[MEMBER]["storageBytes"]
    assert used >= 1000


def test_admins_are_not_limited_and_zero_means_no_limit(admin, member):
    admin.patch("/api/admin/instance", json={"storageLimitMb": 1})
    assert admin.post("/api/files", files={"file": ("big.txt", b"x" * 1_100_000, "text/plain")}).status_code == 200
    admin.patch("/api/admin/instance", json={"storageLimitMb": 0})
    assert member.post("/api/files", files={"file": ("big.txt", b"x" * 1_100_000, "text/plain")}).status_code == 200

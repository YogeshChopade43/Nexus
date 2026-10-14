"""Who owns what: every query acts for one person, and an install's existing data goes to its first account."""
from __future__ import annotations

import pytest

from app.auth import owner, store
from app.auth.context import current_user
from app.core.database import get_connection, init_db


@pytest.fixture
def no_accounts():
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    yield


def test_with_nobody_signed_in_there_is_no_owner():
    token = current_user.set(None)  # a background job that forgot as_user()
    try:
        with pytest.raises(RuntimeError, match="no signed-in user"):
            owner.owner_id()  # never "everyone's rows" by accident
    finally:
        current_user.reset(token)


def test_a_background_job_acts_as_its_owner(no_accounts):
    ana = store.create_user("ana@example.com", "correct horse battery")
    before = current_user.get()
    with owner.as_user(ana["id"]):
        assert owner.owner_id() == ana["id"]
    assert current_user.get() is before  # restored afterwards


@pytest.mark.sqlite_only
def test_the_first_account_gets_the_install_s_existing_data(no_accounts):
    conn = get_connection()
    try:
        for table in owner.OWNED_TABLES:
            assert "user_id" in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}, table
        conn.execute("INSERT INTO memories (content, created_at, source) VALUES ('likes tea', '2026-01-01', 'manual')")
        conn.execute("UPDATE memories SET user_id = NULL")
        conn.commit()
    finally:
        conn.close()
    ana = store.create_user("ana@example.com", "correct horse battery")
    bo = store.create_user("bo@example.com", "correct horse battery")
    conn = get_connection()
    try:
        owners = {row["user_id"] for row in conn.execute("SELECT user_id FROM memories")}
    finally:
        conn.close()
    assert owners == {ana["id"]} and bo["id"] not in owners  # the second account starts empty

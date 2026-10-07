"""The dev-key fallback must never silently replace the key that encrypted existing data."""
from __future__ import annotations

import sqlite3

import pytest

from app.core.config import ensure_secret_key


def _db_with(tmp_path, api_key: str) -> str:
    path = tmp_path / "nexus.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE llm_providers (id INTEGER PRIMARY KEY, api_key TEXT)")
    conn.execute("INSERT INTO llm_providers (api_key) VALUES (?)", (api_key,))
    conn.commit()
    conn.close()
    return str(path)


def test_generates_key_for_fresh_database(tmp_path):
    environ: dict[str, str] = {}
    ensure_secret_key(str(tmp_path / "nexus.db"), environ)
    assert environ["NEXUS_SECRET_KEY"]
    assert (tmp_path / ".nexus_secret_key").read_text().strip() == environ["NEXUS_SECRET_KEY"]


def test_refuses_to_generate_when_encrypted_data_exists(tmp_path):
    environ: dict[str, str] = {}
    with pytest.raises(SystemExit) as exc:
        ensure_secret_key(_db_with(tmp_path, "fernet-llm:abc"), environ)
    assert "NEXUS_SECRET_KEY" in str(exc.value)
    assert "NEXUS_SECRET_KEY" not in environ
    assert not (tmp_path / ".nexus_secret_key").exists()


def test_existing_key_file_is_reused(tmp_path):
    (tmp_path / ".nexus_secret_key").write_text("kept")
    environ: dict[str, str] = {}
    ensure_secret_key(_db_with(tmp_path, "fernet-llm:abc"), environ)
    assert environ["NEXUS_SECRET_KEY"] == "kept"


def test_decrypt_error_explains_the_fix(monkeypatch):
    from app.core import secrets

    monkeypatch.setenv("NEXUS_SECRET_KEY", "key-one")
    stored = secrets.encrypt_api_key("sk-test")
    monkeypatch.setenv("NEXUS_SECRET_KEY", "key-two")
    with pytest.raises(ValueError) as exc:
        secrets.decrypt_api_key(stored)
    assert "different NEXUS_SECRET_KEY" in str(exc.value)
    assert "Settings" in str(exc.value)

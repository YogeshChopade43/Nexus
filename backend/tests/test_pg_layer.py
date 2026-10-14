"""The PostgreSQL connection: the app's SQLite-flavoured SQL, translated, on a real (private, throwaway) PostgreSQL."""
from __future__ import annotations

import logging
import sqlite3
import tempfile

import pytest

from app.core import pg


def test_placeholders_become_postgres_ones_but_never_inside_text():
    assert pg.translate("SELECT * FROM t WHERE a = ? AND b LIKE '%x?%'") == "SELECT * FROM t WHERE a = %s AND b ILIKE '%%x?%%'"
    assert pg.translate("WHERE user_id = :owner AND title LIKE :p ESCAPE '!'") == "WHERE user_id = %(owner)s AND title ILIKE %(p)s ESCAPE '!'"
    assert pg.translate("SELECT 'it''s ?' , ?") == "SELECT 'it''s ?' , %s"
    assert pg.translate("SELECT '12:30', :x") == "SELECT '12:30', %(x)s"  # a time in text isn't a parameter


def test_sqlite_only_phrases_get_their_postgres_form():
    assert pg.translate("INSERT OR IGNORE INTO t (a) VALUES (?)") == "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING"
    assert "now()" in pg.translate("UPDATE t SET updated_at = datetime('now') WHERE id = ?")
    assert pg.translate("SELECT id FROM c WHERE name = ? COLLATE NOCASE") == "SELECT id FROM c WHERE lower(name) = lower(%s)"
    assert pg.translate("WHERE title LIKE ? AND body NOT LIKE ?") == "WHERE title ILIKE %s AND body NOT ILIKE %s"  # SQLite's LIKE ignores case
    assert pg.translate("WHERE a IS ? AND b IS NOT :x AND c IS NULL") == (
        "WHERE a IS NOT DISTINCT FROM %s AND b IS DISTINCT FROM %(x)s AND c IS NULL")  # SQLite's null-safe compare
    assert pg.translate("INSERT OR REPLACE INTO cache (key, vector) VALUES (?, ?)") == (
        "INSERT INTO cache (key, vector) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET vector = EXCLUDED.vector")


@pytest.fixture(scope="module")
def server():
    pgserver = pytest.importorskip("pgserver")
    logging.getLogger("pgserver").setLevel(logging.WARNING)  # its shutdown logs after pytest closed the output
    yield pgserver.get_server(tempfile.mkdtemp(prefix="nexus-pg-test-"), cleanup_mode="stop")


@pytest.fixture(scope="module")
def database(server):
    yield server.get_uri()


def test_a_round_trip_works_like_sqlite(database):
    conn = pg.connect(database)
    try:
        conn.executescript("DROP TABLE IF EXISTS pets; CREATE TABLE pets (id SERIAL PRIMARY KEY, name TEXT UNIQUE, legs INTEGER);")
        cursor = conn.execute("INSERT INTO pets (name, legs) VALUES (?, ?)", ("Rex", 4))
        assert cursor.lastrowid == 1
        conn.execute("INSERT OR IGNORE INTO pets (name, legs) VALUES (?, ?)", ("Rex", 3))  # ignored, no error
        conn.commit()
        row = conn.execute("SELECT * FROM pets WHERE name = ?", ("Rex",)).fetchone()
        assert row["legs"] == 4 and row[1] == "Rex" and dict(row) == {"id": 1, "name": "Rex", "legs": 4}
        assert "legs" in row.keys()
        name, legs = conn.execute("SELECT name, legs FROM pets").fetchone()  # unpacks values, as sqlite3.Row does
        assert (name, legs) == ("Rex", 4) and {**row}["legs"] == 4
        conn.execute("BEGIN IMMEDIATE")  # SQLite's write lock: PostgreSQL is already in a transaction
        assert [r["name"] for r in conn.execute("SELECT name FROM pets")] == ["Rex"]
        assert conn.execute("UPDATE pets SET legs = :n WHERE name = :name", {"n": 3, "name": "Rex"}).rowcount == 1
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM pets").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):  # the app's existing `except sqlite3.IntegrityError` still works
            conn.execute("INSERT INTO pets (name, legs) VALUES (?, ?)", ("Rex", 2))
        conn.rollback()
        assert conn.execute("SELECT legs FROM pets").fetchone()[0] == 3
    finally:
        conn.close()


def _columns_on_sqlite(monkeypatch, tmp_path) -> dict[str, set[str]]:
    from app.core.database import get_connection, init_db

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fresh.db"))
    init_db()
    conn = get_connection()
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND sql NOT LIKE 'CREATE VIRTUAL%' "
                                             "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'legacy_%'")]
        tables = [t for t in tables if not t.startswith(("chunk_fts_", "registry_fts_"))]  # FTS5's own storage
        return {t: {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    finally:
        conn.close()


def test_a_fresh_postgres_install_has_sqlite_s_schema_and_restarts_cleanly(server, monkeypatch, tmp_path):
    from app.core.database import get_connection, init_db

    expected = _columns_on_sqlite(monkeypatch, tmp_path)
    server.psql("DROP DATABASE IF EXISTS fresh; CREATE DATABASE fresh;")
    monkeypatch.setenv("DATABASE_URL", server.get_uri("fresh"))
    init_db()
    init_db()  # a restart: nothing to do, nothing breaks
    conn = get_connection()
    try:
        actual: dict[str, set[str]] = {}
        for row in conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"):
            actual.setdefault(row["table_name"], set()).add(row["column_name"])
        assert conn.execute("SELECT name FROM workspaces WHERE id = 1").fetchone()["name"] == "Default"
        assert conn.execute("INSERT INTO workspaces (name) VALUES ('Next')").lastrowid == 2  # the seeded id is taken
    finally:
        conn.close()
    postgres_only = {"schema_version", "chunk_fts", "registry_fts", "chunk_vectors"}  # SQLite: FTS5/sqlite-vec tables
    assert {t: c for t, c in actual.items() if t not in postgres_only} == expected  # regenerate schema_postgres.sql if not

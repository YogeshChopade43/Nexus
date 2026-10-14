"""PostgreSQL behind the sqlite3-style API the app is written against.

``connect(url)`` returns a connection with the part of sqlite3's API Nexus uses (``execute``, ``executescript``,
``commit``, ``rollback``, ``close``, cursors with ``fetchone`` / ``fetchall`` / iteration / ``rowcount`` /
``lastrowid``, rows readable as ``row["x"]``, ``row[0]``, ``keys()`` and ``dict(row)``), so the same SQL runs on
SQLite (local, tests) and PostgreSQL (production). ``translate`` turns the SQLite flavour into PostgreSQL's:

- ``?`` -> ``%s`` and ``:name`` -> ``%(name)s`` (never inside 'text'), and a literal ``%`` -> ``%%``
- ``INSERT OR IGNORE`` -> ``INSERT … ON CONFLICT DO NOTHING``; ``datetime('now')`` -> UTC now as text
- ``INSERT OR REPLACE INTO t (key, …)`` -> an upsert on its first column (always the key, in Nexus)
- ``LIKE`` -> ``ILIKE`` (SQLite's LIKE ignores case)
- ``x IS ?`` -> ``x IS NOT DISTINCT FROM ?`` (SQLite's null-safe comparison)
- ``x = ? COLLATE NOCASE`` -> ``lower(x) = lower(?)``
- an INSERT into a table with an ``id`` column gets ``RETURNING id``, which is ``lastrowid``
A unique-key violation is raised as ``sqlite3.IntegrityError``, so existing ``except`` clauses keep working.

ponytail: a new connection per get_connection() call (as with SQLite); add psycopg_pool if connection setup shows up.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterator, Optional, Sequence

_NOW = "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"
_INSERT_INTO = re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", re.IGNORECASE)


def _rewrite_phrases(sql: str) -> str:
    """SQLite-only phrases in their PostgreSQL form (before placeholders are converted)."""
    ignore = re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.IGNORECASE)
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE)
    sql = re.sub(r"datetime\('now'\)", _NOW, sql, flags=re.IGNORECASE)
    sql = re.sub(r"([\w.]+)\s*=\s*\?\s+COLLATE\s+NOCASE", r"lower(\1) = lower(?)", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bIS\s+NOT\s+(?=\?|:\w)", "IS DISTINCT FROM ", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bIS\s+(?=\?|:\w)", "IS NOT DISTINCT FROM ", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\b(NOT\s+)?LIKE\b",lambda m: (m.group(1) or "") + "ILIKE", sql, flags=re.IGNORECASE)
    if ignore:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    replace = re.match(r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]*)\)", sql, re.IGNORECASE)
    if replace:
        key, *rest = [c.strip() for c in replace.group(2).split(",")]
        sql = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql.rstrip().rstrip(";"), flags=re.IGNORECASE)
        sql += f" ON CONFLICT ({key}) DO " + ("UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in rest) if rest else "NOTHING")
    return sql


def _convert_placeholders(sql: str) -> str:
    out, i, in_text = [], 0, False
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            in_text = not in_text
            out.append(ch)
        elif ch == "%":
            out.append("%%")
        elif in_text:
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == ":" and i + 1 < len(sql) and (sql[i + 1].isalpha() or sql[i + 1] == "_") and (i == 0 or sql[i - 1] != ":"):
            name = re.match(r"\w+", sql[i + 1:]).group(0)
            out.append(f"%({name})s")
            i += len(name)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def translate(sql: str) -> str:
    return _convert_placeholders(_rewrite_phrases(sql))


class Row(dict):
    """A result row readable like sqlite3.Row: by name, by position, ``keys()`` and ``dict(row)``."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key: Any) -> Any:
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)

    def keys(self) -> list[str]:  # type: ignore[override]
        return list(super().keys())

    def __iter__(self) -> Iterator[Any]:  # values, so ``a, b = row`` unpacks as with sqlite3.Row
        return iter(self._values)


class Cursor:
    def __init__(self, cursor: Any, lastrowid: Optional[int] = None, prefetched: Optional[list[Row]] = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount
        self._prefetched = prefetched

    def _columns(self) -> list[str]:
        return [d.name for d in self._cursor.description or []]

    def fetchone(self) -> Optional[Row]:
        if self._prefetched is not None:
            return self._prefetched.pop(0) if self._prefetched else None
        if self._cursor.description is None:
            return None
        values = self._cursor.fetchone()
        return Row(self._columns(), values) if values is not None else None

    def fetchall(self) -> list[Row]:
        if self._prefetched is not None:
            rows, self._prefetched = self._prefetched, []
            return rows
        if self._cursor.description is None:
            return []
        columns = self._columns()
        return [Row(columns, values) for values in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Connection:
    """The sqlite3.Connection subset Nexus uses, on PostgreSQL."""

    _id_columns: dict[str, bool] = {}  # table -> has an ``id`` column (for lastrowid)

    def __init__(self, url: str) -> None:
        import psycopg

        self._conn = psycopg.connect(url)
        self.row_factory = None  # accepted for compatibility; rows are always Row

    def _has_id(self, table: str) -> bool:
        table = table.lower()
        if table not in self._id_columns:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'id'", (table,))
                self._id_columns[table] = cur.fetchone() is not None
        return self._id_columns[table]

    def execute(self, sql: str, params: Any = ()) -> Cursor:
        import psycopg

        if re.match(r"\s*BEGIN\b", sql, re.IGNORECASE):
            return Cursor(self._conn.cursor())  # already in a transaction (SQLite's BEGIN IMMEDIATE takes its write lock)
        insert = _INSERT_INTO.match(sql)
        wants_id = bool(insert) and "RETURNING" not in sql.upper() and self._has_id(insert.group(1))
        query = translate(sql) + (" RETURNING id" if wants_id else "")
        cursor = self._conn.cursor()
        try:
            cursor.execute(query, params if params is not None else ())
        except psycopg.errors.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc
        if wants_id:
            row = cursor.fetchone()
            return Cursor(cursor, lastrowid=row[0] if row else None, prefetched=[])
        return Cursor(cursor)

    def executemany(self, sql: str, rows: Any) -> None:
        for params in rows:
            self.execute(sql, params)

    def executescript(self, sql: str) -> None:
        """Several statements at once (schema), no parameters."""
        with self._conn.cursor() as cursor:
            cursor.execute(_rewrite_phrases(sql))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, kind: Any, *rest: Any) -> None:
        if kind is None:
            self.commit()
        else:
            self.rollback()


def connect(url: str) -> Connection:
    return Connection(url)

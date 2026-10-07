from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.core.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return get_connection()


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if parsed is not None else default


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

DEFAULT_USER_SETTINGS = {
    "theme": "dark",
    "language": "en-US",
    "timezone": "America/New_York",
    "notifications": {
        "email": True,
        "push": True,
        "workflowCompletion": True,
        "workflowFailure": True,
        "appUpdates": True,
        "mentions": True,
    },
    "privacy": {
        "analytics": True,
        "crashReporting": True,
        "dataSharing": False,
    },
    "editor": {
        "fontSize": 14,
        "fontFamily": "monospace",
        "tabSize": 2,
        "wordWrap": True,
        "minimap": False,
        "lineNumbers": True,
    },
}


DEFAULT_API_SETTINGS = {"baseUrl": "http://localhost:8000", "timeout": 30, "retries": 3}


def _read_api_settings(conn) -> dict[str, Any]:
    row = conn.execute("SELECT settings FROM api_settings ORDER BY id LIMIT 1").fetchone()
    stored = _load_json(row["settings"], {}) if row else {}
    return {**DEFAULT_API_SETTINGS, **stored}


def _get_user_settings_row(conn) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM user_settings ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return None
    return dict(row)


def _read_user_settings(conn) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_USER_SETTINGS)
    row = _get_user_settings_row(conn)
    if row:
        _deep_merge(merged, _load_json(row.get("settings"), {}))
    return merged


@router.get("/")
def get_settings() -> dict[str, Any]:
    conn = _conn()
    try:
        user = _read_user_settings(conn)

        api = _read_api_settings(conn)

        return {
            "user": user,
            "api": api,
        }
    finally:
        conn.close()


@router.get("/user")
def get_user_settings() -> dict[str, Any]:
    conn = _conn()
    try:
        return _read_user_settings(conn)
    finally:
        conn.close()


@router.patch("/user")
def update_user_settings(settings: dict[str, Any]) -> dict[str, Any]:
    conn = _conn()
    try:
        row = _get_user_settings_row(conn)
        if row is None:
            conn.execute(
                "INSERT INTO user_settings (settings, updated_at) VALUES (?, ?)",
                (json.dumps(settings), _utc_now()),
            )
            conn.commit()
            return settings

        merged = _read_user_settings(conn)
        _deep_merge(merged, settings)
        conn.execute(
            "UPDATE user_settings SET settings = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), _utc_now(), row["id"]),
        )
        conn.commit()
        return merged
    finally:
        conn.close()


@router.get("/api")
def get_api_settings() -> dict[str, Any]:
    conn = _conn()
    try:
        return _read_api_settings(conn)
    finally:
        conn.close()


@router.patch("/api")
def update_api_settings(settings: dict[str, Any]) -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM api_settings ORDER BY id LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO api_settings (settings, updated_at) VALUES (?, ?)",
                (json.dumps(settings), _utc_now()),
            )
            conn.commit()
            return settings

        merged = _load_json(row["settings"], dict(DEFAULT_API_SETTINGS))
        _deep_merge(merged, settings)
        conn.execute(
            "UPDATE api_settings SET settings = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), _utc_now(), row["id"]),
        )
        conn.commit()
        return merged
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
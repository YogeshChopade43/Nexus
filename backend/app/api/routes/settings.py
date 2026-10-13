from __future__ import annotations

import copy
import io
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.middleware import require_local
from app.core.database import get_connection, log_activity

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
    "retentionDays": 30,  # runs and activity older than this are deleted daily; 0 keeps everything
    "notificationsReadAt": None,  # notifications up to this time have been seen
    "ragRerank": True,  # rerank document search results with the local cross-encoder
    "dailyTokenLimit": 0,  # AI tokens per day (UTC) across chat and workflows; 0 = no limit
    "llmPrices": {},  # model -> {"input": $, "output": $} per million tokens, for cost estimates
    "timezone": "UTC",  # IANA name; schedules without their own timezone use it
    "notifications": {"workflowFailure": True},  # failed runs show in the bell
    "memory": {"auto": True},  # learn lasting facts from chats by itself (every few messages)
    # The daily briefing's choices; it runs as the workflow ``workflowId``.
    "briefing": {"workflowId": None, "time": "08:00", "weekdaysOnly": True,
                 "sections": ["calendar", "email", "apps", "feeds"], "notes": ""},
}


def _known(settings: dict[str, Any], defaults: dict[str, Any] = DEFAULT_USER_SETTINGS) -> dict[str, Any]:
    """Only settings Nexus uses: options removed from the app (language, privacy, editor...) stay out."""
    return {key: _known(value, defaults[key]) if isinstance(defaults[key], dict) and isinstance(value, dict)
            and key != "llmPrices" else value
            for key, value in settings.items() if key in defaults}


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


def normalize_timezone(name: Any) -> str:
    """A valid IANA timezone: the name itself, the zone it is the city of ("Kolkata"), or UTC."""
    zones = available_timezones()
    name = str(name or "").strip()
    if name in zones:
        return name
    return next((z for z in sorted(zones) if z.lower().endswith("/" + name.lower().replace(" ", "_"))), "UTC") if name else "UTC"


def _read_user_settings(conn) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_USER_SETTINGS)
    row = _get_user_settings_row(conn)
    if row:
        _deep_merge(merged, _load_json(row.get("settings"), {}))
    merged["timezone"] = normalize_timezone(merged.get("timezone"))
    return _known(merged)


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
    if "timezone" in settings and settings["timezone"] not in available_timezones():
        raise HTTPException(status_code=422, detail=f"Unknown timezone '{settings['timezone']}'. Choose one like Asia/Kolkata.")
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

def user_timezone() -> str:
    return load_user_settings()["timezone"]


def load_user_settings() -> dict[str, Any]:
    conn = _conn()
    try:
        return _read_user_settings(conn)
    finally:
        conn.close()


@router.get("/backup")
def download_backup(request: Request) -> Response:
    """A zip with a consistent copy of the database and the key that decrypts its secrets."""
    require_local(request, "Backups contain every stored secret, so they can only be downloaded on the machine running Nexus.")
    with tempfile.TemporaryDirectory() as folder:
        copy_path = Path(folder) / "nexus.db"
        source, target = _conn(), sqlite3.connect(copy_path)
        try:
            source.backup(target)  # safe while Nexus keeps writing
        finally:
            target.close()
            source.close()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy_path, "nexus.db")
            archive.writestr("NEXUS_SECRET_KEY.txt", os.getenv("NEXUS_SECRET_KEY", ""))
            archive.writestr("RESTORE.txt", RESTORE_STEPS)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    log_activity("settings_changed", "Backup downloaded")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="nexus-backup-{stamp}.zip"'})


RESTORE_STEPS = """To restore this backup:
1. Stop the Nexus backend.
2. Copy nexus.db over backend/data/nexus.db (or the file DATABASE_PATH points to).
3. Put the key from NEXUS_SECRET_KEY.txt in backend/.env as NEXUS_SECRET_KEY=<key>
   (or in backend/data/.nexus_secret_key). Without that exact key the stored secrets can't be read.
4. Start the backend.
Keep this file private: with the key, anyone can read every stored token and API key.
"""

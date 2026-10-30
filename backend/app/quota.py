"""Instance-wide settings the admin controls, and the storage quota they set for everyone else."""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from app.core.database import get_connection, get_db_path

# signups None: NEXUS_SIGNUPS decides. privacyUrl / termsUrl: the operator's own policies, linked on the sign-in page.
DEFAULT_INSTANCE = {"signups": None, "storageLimitMb": 1024, "privacyUrl": "", "termsUrl": ""}


class StorageFull(Exception):
    """An upload would take someone past the storage limit (answered as 413)."""


def instance() -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT settings FROM api_settings ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    stored = json.loads(row["settings"] or "{}") if row else {}
    return {key: stored.get(key, default) for key, default in DEFAULT_INSTANCE.items()}


def save_instance(changes: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, settings FROM api_settings ORDER BY id LIMIT 1").fetchone()
        settings = {**(json.loads(row["settings"] or "{}") if row else {}), **changes}
        if row:
            conn.execute("UPDATE api_settings SET settings = ?, updated_at = datetime('now') WHERE id = ?",
                         (json.dumps(settings), row["id"]))
        else:
            conn.execute("INSERT INTO api_settings (settings) VALUES (?)", (json.dumps(settings),))
        conn.commit()
    finally:
        conn.close()
    return instance()


def signups_setting() -> bool:
    """Anyone can sign up, unless the admin closed it (Settings › Admin) or the server sets NEXUS_SIGNUPS=closed."""
    choice = instance()["signups"]
    return choice == "open" if choice else os.getenv("NEXUS_SIGNUPS", "").lower() != "closed"


def storage_used(user_id: int) -> int:
    """Bytes of someone's documents and files."""
    conn = get_connection()
    try:
        documents = conn.execute("SELECT COALESCE(SUM(d.size_bytes), 0) FROM documents d JOIN workspaces w "
                                 "ON w.id = d.workspace_id WHERE w.user_id = ?", (user_id,)).fetchone()[0]
    finally:
        conn.close()
    folder = get_db_path().parent / "files" / str(user_id)
    files = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0
    return int(documents) + files


def check_storage(adding: int, user: Optional[dict[str, Any]] = None) -> None:
    """Refuse ``adding`` more bytes for the acting person when it takes them past the limit (admins: no limit)."""
    from app.auth.context import current_user

    user = user or current_user.get()
    limit_mb = int(instance()["storageLimitMb"] or 0)
    if not user or user.get("is_admin") or not limit_mb:
        return
    used = storage_used(int(user["id"]))
    if used + adding > limit_mb * 1024 * 1024:
        raise StorageFull(f"That would go past your {limit_mb:,} MB of storage ({used / 1048576:.1f} MB used). "
                          "Delete documents or files you no longer need, or ask the admin for more.")

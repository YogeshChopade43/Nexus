from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.database import get_connection
from app.models.app import AppBase
from app.apps.registry import APPS_REGISTRY


def seed_apps_if_empty() -> None:
    conn = get_connection()
    try:
        existing = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
        if existing > 0:
            return
        for app_data in APPS_REGISTRY:
            app = AppBase(**{k: v for k, v in app_data.items() if k not in ("capabilities",)})
            conn.execute(
                "INSERT INTO apps (app_id, name, description, category, icon, enabled, capabilities) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (app.app_id, app.name, app.description, app.category, app.icon, int(app.enabled), json.dumps(app_data.get("capabilities", []))),
            )
        conn.commit()
    finally:
        conn.close()
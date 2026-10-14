from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from app.auth.owner import owner_id
from app.core.database import get_connection
from app.llm.metering import Metered
from app.llm.registry import LLMRegistry


def get_active_llm_provider(provider_id: Optional[int] = None, provider_name: Optional[str] = None):
    """Resolve an LLM provider instance from the database.

    Returns a tuple of (provider_instance, config_dict) or raises HTTPException.
    """
    conn = get_connection()
    try:
        if provider_id is not None:
            row = conn.execute(
                "SELECT * FROM llm_providers WHERE id = ? AND enabled = 1 AND user_id = ?",
                (provider_id, owner_id()),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=400, detail="LLM provider not found or disabled")
        elif provider_name:
            row = conn.execute(
                "SELECT * FROM llm_providers WHERE provider_name = ? AND enabled = 1 AND user_id = ? ORDER BY id DESC LIMIT 1",
                (provider_name, owner_id()),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=400, detail=f"No enabled LLM provider named '{provider_name}'")
        else:
            row = conn.execute(
                "SELECT * FROM llm_providers WHERE enabled = 1 AND user_id = ? ORDER BY id DESC LIMIT 1", (owner_id(),)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=400, detail="No LLM provider configured")

        provider_id = row["id"]
    finally:
        conn.close()

    registry = LLMRegistry()
    try:
        provider = registry.get_provider(provider_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not load LLM provider: {exc}")
    config = registry.get_config(provider_id)
    return Metered(provider, provider_id, config), config


def get_default_llm_provider():
    """The most recently added enabled provider as (provider, config), or (None, None)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM llm_providers WHERE enabled = 1 AND user_id = ? ORDER BY id DESC LIMIT 1", (owner_id(),)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None, None
    return get_active_llm_provider(provider_id=row["id"])

"""Who the current request (or background job) is acting for."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from fastapi import HTTPException

current_user: ContextVar[Optional[dict[str, Any]]] = ContextVar("current_user", default=None)


def require_user() -> dict[str, Any]:
    user = current_user.get()
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to use Nexus")
    return user


def require_admin(what: str = "This") -> dict[str, Any]:
    """Instance-wide powers (everyone's data, the server itself) are the admin's only."""
    user = require_user()
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail=f"{what} is only for this Nexus's admin.")
    return user

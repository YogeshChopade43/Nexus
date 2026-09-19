from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ConnectionRequest(BaseModel):
    connected: Optional[bool] = None
    enabled: Optional[bool] = None
    config: dict[str, Any] = {}
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TriggerConfig(BaseModel):
    """Configuration for a workflow trigger.

    Triggers can be granular - e.g. ``github.pull_request.opened`` rather than
    just ``github``. This allows workflows to fire on specific events within
    an app rather than any activity from that app.
    """
    type: str = "manual"  # manual | recurrence | poll | schedule | webhook | app_event
    app_id: Optional[str] = None
    event: Optional[str] = None
    filters: dict[str, Any] = Field(default_factory=dict)
    schedule: Optional[str] = None  # 5-field cron expression ("Advanced")
    timezone: str = "UTC"
    enabled: bool = True
    secret: Optional[str] = None  # webhook token
    concurrency: int = 0  # max simultaneous runs of this workflow; 0 = unlimited
    # manual
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    # recurrence
    frequency: Optional[str] = None  # minute | hour | day | week | month
    interval: int = 1
    at: str = "00:00"
    weekdays: list[str] = Field(default_factory=list)
    month_day: Optional[int] = None  # 1-31, or -1 for the last day of the month
    anchor: Optional[str] = None  # YYYY-MM-DD the "every N days/weeks/months" cycle counts from
    # poll precision
    poll_mode: str = "new"  # new | new_or_updated
    updated_field: str = ""
    created_field: str = ""
    filter_field: str = ""
    filter_operator: str = ""
    filter_value: Optional[Any] = None
    # poll
    tool: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int = 5
    items_path: str = ""
    id_field: str = ""

    @model_validator(mode="before")
    @classmethod
    def _null_means_default(cls, data: Any) -> Any:
        # AI drafts and the editor send null for settings left unset ("timezone": null); use the defaults.
        return {k: v for k, v in data.items() if v is not None} if isinstance(data, dict) else data


class TriggerEvent(BaseModel):
    """An incoming trigger event from an external source."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    trigger_type: str
    app_id: Optional[str] = None
    source: str = "manual"
    event_name: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now)
    workflow_id: Optional[int] = None
    signature_valid: bool = True
    processed: bool = False


class TriggerMatch(BaseModel):
    """Result of matching an event against workflow triggers."""
    matched: bool = False
    workflow_id: Optional[int] = None
    trigger_config: Optional[TriggerConfig] = None
    reason: str = ""
    input_data: dict[str, Any] = Field(default_factory=dict)
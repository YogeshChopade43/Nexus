"""Inputs a user fills in when manually running a workflow (Power Automate's manual trigger)."""
from __future__ import annotations

import re
from typing import Any

TYPES = ("text", "number", "boolean")
MAX_INPUTS = 20
_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,39}$")
_TRUE = {"true", "yes", "1", "on"}
_FALSE = {"false", "no", "0", "off", ""}


def validate_definitions(defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(defs) > MAX_INPUTS:
        raise ValueError(f"a workflow can have at most {MAX_INPUTS} inputs")
    normalized, seen = [], set()
    for definition in defs:
        name = str(definition.get("name", ""))
        if not _NAME.match(name):
            raise ValueError(f"input name '{name}' must start with a letter or _ and use only letters, digits and _")
        if name in seen:
            raise ValueError(f"input name '{name}' is used twice")
        seen.add(name)
        kind = definition.get("type", "text")
        if kind not in TYPES:
            raise ValueError(f"input '{name}' has unknown type '{kind}' (use text, number or boolean)")
        normalized.append({
            "name": name,
            "type": kind,
            "required": bool(definition.get("required", False)),
            "default": definition.get("default", None),
        })
    return normalized


def _coerce_one(kind: str, value: Any) -> Any:
    if kind == "number":
        if isinstance(value, bool):
            raise ValueError("must be a number")
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                raise ValueError("must be a number")
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError("must be yes/no (true or false)")
    return "" if value is None else str(value)


def coerce(defs: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for definition in defs:
        name = definition["name"]
        value = values.get(name)
        if value is None or value == "":
            if definition.get("default") not in (None, ""):
                value = definition["default"]
            elif definition.get("required"):
                raise ValueError(f"{name}: a value is required")
            else:
                continue
        try:
            result[name] = _coerce_one(definition.get("type", "text"), value)
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}")
    return result

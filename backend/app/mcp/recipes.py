"""Install recipes for MCP Registry entries: the form fields a server needs, and its connection settings.

Nexus connects to hosted MCP servers only, so ``plan(server)`` uses the listing's streamable-HTTP
remote. Listings that would have to run on this computer (npm/PyPI/Docker packages), SSE-only
remotes and listings with no install info return None. ``fill(recipe, values)`` turns the
recipe plus the user's answers into a server config.
"""
from __future__ import annotations

import re
from typing import Any, Optional, TypedDict

PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_\-]+)\}")


class Field(TypedDict):
    key: str
    label: str
    description: str
    required: bool
    secret: bool
    default: str


class _Fields:
    """Collects form fields while the template is built; the first occurrence of a key wins."""

    def __init__(self) -> None:
        self.fields: list[Field] = []

    def add(self, key: str, item: dict[str, Any], default: Any = "") -> None:
        if any(f["key"] == key for f in self.fields):
            return
        self.fields.append({"key": key, "label": key, "description": str(item.get("description") or ""),
                            "required": bool(item.get("isRequired")), "secret": bool(item.get("isSecret")),
                            "default": "" if default is None else str(default)})

    def text(self, text: str, item: dict[str, Any]) -> str:
        """A fixed value: each {placeholder} in it becomes a field (described by item.variables when given)."""
        variables = item.get("variables") or {}
        for key in PLACEHOLDER.findall(text):
            meta = variables.get(key) if isinstance(variables.get(key), dict) else item
            self.add(key, meta, meta.get("default", "") if meta is not item else "")
        return text

    def value(self, item: dict[str, Any]) -> str:
        """A header: its value, or a field named after it."""
        if item.get("value") is not None:
            return self.text(str(item["value"]), item)
        self.add(item["name"], item, item.get("default", ""))
        return "{" + item["name"] + "}"


def plan(server: dict[str, Any]) -> Optional[dict[str, Any]]:
    for remote in server.get("remotes") or []:
        if remote.get("type") == "streamable-http" and remote.get("url"):
            fields = _Fields()
            url = fields.text(remote["url"], remote)
            headers = {h["name"]: fields.value(h) for h in remote.get("headers") or [] if h.get("name")}
            return {"kind": "hosted", "fields": fields.fields, "template": {"url": url, "headers": headers}}
    return None


def fill(recipe: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    answers: dict[str, str] = {}
    for field in recipe["fields"]:
        answer = str(values.get(field["key"]) or "").strip() or field["default"]
        if field["required"] and not answer:
            raise ValueError(f"{field['label']} is required")
        answers[field["key"]] = answer

    def sub(text: str) -> tuple[str, bool]:
        """Text with placeholders filled, and whether any of them was left empty."""
        empty = any(not answers.get(key) for key in PLACEHOLDER.findall(text) if key in answers)
        return PLACEHOLDER.sub(lambda m: answers.get(m.group(1), m.group(0)), text), empty

    headers = {key: sub(value) for key, value in recipe["template"]["headers"].items()}
    return {"transport": "http", "url": sub(recipe["template"]["url"])[0],
            "headers": {key: text for key, (text, empty) in headers.items() if text and not empty}}


if __name__ == "__main__":
    hosted = plan({"remotes": [{"type": "streamable-http", "url": "https://x/mcp",
                                "headers": [{"name": "Authorization", "value": "Bearer {key}", "isRequired": True}]}]})
    assert hosted and fill(hosted, {"key": "k"})["headers"] == {"Authorization": "Bearer k"}
    assert plan({"packages": [{"registryType": "npm", "identifier": "p", "transport": {"type": "stdio"}}]}) is None
    print("recipe self-check passed")

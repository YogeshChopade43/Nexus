"""Sharing workflows: an export safe to send to someone, and an import that works on their Nexus.

Exporting leaves out secrets (API keys and tokens in steps) and this install's own ids, and says which apps the
steps use by what identifies them anywhere: a built-in app's kind (Gmail, Telegram…) or an MCP server's address.
Importing points those steps at the receiver's own matching app, and lists what they still need to connect or fill in.
"""
from __future__ import annotations

import copy
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Names of settings that hold secrets: "Authorization", "X-Api-Key", "api_key", "token", "password"… (not "max_tokens").
SECRET = re.compile(r"authorization|cookie|secret|password|passwd|token$|^token|api[-_]?key|apikey|access[-_]?key|^key$",
                    re.IGNORECASE)
LOCAL_IDS = ("provider_id", "library_id", "collection_id")  # ids that only mean something on this install


def _is_secret(name: str, value: Any) -> bool:
    return bool(SECRET.search(str(name))) and isinstance(value, str) and bool(value.strip()) and "{{" not in value


def _clear(values: Any, where: str, cleared: list[str]) -> Any:
    """Blank secret-named values anywhere in a step's settings (headers, parameters…)."""
    if isinstance(values, dict):
        out = {}
        for key, value in values.items():
            if _is_secret(key, value):
                out[key] = ""
                cleared.append(f"{where}: {key}")
            else:
                out[key] = _clear(value, where, cleared)
        return out
    if isinstance(values, list):
        return [_clear(v, where, cleared) for v in values]
    return values


def _clear_url(url: Any, where: str, cleared: list[str]) -> Any:
    if not isinstance(url, str) or "?" not in url:
        return url
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_secret(key, value):
            cleared.append(f"{where}: {key} in the address")
            value = ""
        query.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _app_of(config: dict[str, Any]) -> str:
    tool = str(config.get("tool") or "")
    return tool.split("__", 1)[0] if "__" in tool else ""


def _local_apps() -> dict[str, dict[str, Any]]:
    """This install's apps by slug: what identifies each one on any Nexus."""
    from app.integrations import store as integrations
    from app.mcp import store as servers

    apps: dict[str, dict[str, Any]] = {}
    for server in servers.list_servers():
        apps[server.slug] = {"name": server.name, **({"url": server.url} if server.url else {"command": server.command})}
    for integration in integrations.list_integrations():
        apps[integration["slug"]] = {"name": integration["name"], "integration": integration["kind"]}
    return apps


def shareable(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """(nodes without secrets or local ids, the apps they use, what was left out)."""
    nodes, cleared, used = copy.deepcopy(nodes), [], set()
    for node in nodes:
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        where = str(node.get("name") or node.get("id") or "a step")
        for key in LOCAL_IDS:
            config.pop(key, None)
        if node.get("type") == "workflow" and config.pop("workflow_id", None) is not None:
            cleared.append(f"{where}: which of your workflows it runs")
        if "url" in config:
            config["url"] = _clear_url(config["url"], where, cleared)
        node["config"] = _clear(config, where, cleared)
        if app := _app_of(config):
            used.add(app)
    local = _local_apps()
    return nodes, {slug: local[slug] for slug in sorted(used) if slug in local}, cleared


def _same_app(theirs: dict[str, Any], mine: dict[str, Any]) -> bool:
    if theirs.get("integration"):
        return theirs["integration"] == mine.get("integration")
    if theirs.get("url"):
        return str(theirs["url"]).rstrip("/") == str(mine.get("url") or "").rstrip("/")
    return bool(theirs.get("command")) and theirs.get("command") == mine.get("command")


def adopt(nodes: list[dict[str, Any]], apps: dict[str, Any], cleared: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Point an imported workflow's steps at this install's matching apps; notes on what's still needed."""
    nodes, notes = copy.deepcopy(nodes), []
    local = _local_apps()
    rename: dict[str, str] = {}
    for slug, identity in (apps or {}).items():
        if not isinstance(identity, dict):
            continue
        matches = [mine for mine, info in local.items() if _same_app(identity, info)]
        if matches:
            rename[slug] = slug if slug in matches else matches[0]
        else:
            notes.append(f"Connect {identity.get('name') or slug} in the Marketplace: a step uses it.")
    for node in nodes:
        config = node.get("config")
        if isinstance(config, dict) and (app := _app_of(config)) in rename and rename[app] != app:
            config["tool"] = f"{rename[app]}__{config['tool'].split('__', 1)[1]}"
    notes += [f"Add your own: {item}" for item in cleared or []]
    return nodes, notes

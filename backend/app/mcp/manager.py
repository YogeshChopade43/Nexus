"""Keeps one live MCP session per enabled server and exposes its tools to Nexus.

Each server runs in its own asyncio task that owns the ``mcp.Client`` context (the SDK
requires entering and exiting it in the same task). While connected, the server's tools
are registered in the shared ToolRegistry as ``<slug>__<tool>``; when the session drops
they are removed and the task reconnects with exponential backoff.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from collections import deque
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import anyio
import mcp.types as mcp_types
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.subscriptions import ListenNotSupportedError
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from app.core.config import PORT
from app.core.database import get_db_path, log_activity
from app.core.exceptions import AppNotConnectedError
from app.mcp import store
from app.mcp.store import ServerConfig, list_servers
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 60  # first npx/uvx launch may download the package
CALL_TIMEOUT = 120
MAX_BACKOFF = 300
SIGN_IN_TIMEOUT = 600  # how long a hosted server waits for you to finish signing in
MAX_LOG_BYTES = 512_000
# Where the browser comes back after signing in to a hosted server; must reach this backend.
PUBLIC_URL = os.getenv("NEXUS_PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
OAUTH_CALLBACK_URL = f"{PUBLIC_URL}/api/mcp/servers/oauth/callback"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_path(slug: str) -> Path:
    """File that receives a local server's stderr (its own logs and crash output)."""
    folder = get_db_path().parent / "mcp-logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{slug}.log"


def read_log_tail(slug: str, max_bytes: int = 32_000) -> str:
    path = log_path(slug)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def server_said(slug: str) -> str:
    """The last line a local server wrote to its error output in its latest run (why it stopped, usually)."""
    latest = read_log_tail(slug, 8_000).rsplit("--- ", 1)[-1].split("---", 1)[-1]  # after the last "starting" marker
    lines = [line.strip() for line in latest.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


class _TokenStorage:
    """Keeps a hosted server's OAuth tokens and client registration in the database, encrypted."""

    def __init__(self, server_id: int) -> None:
        self._id = server_id

    def _update(self, key: str, value: Any) -> None:
        data = store.get_oauth(self._id)
        data[key] = value.model_dump(mode="json", exclude_none=True)
        store.set_oauth(self._id, data)

    async def get_tokens(self) -> Optional[OAuthToken]:
        data = store.get_oauth(self._id).get("tokens")
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._update("tokens", tokens)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        data = store.get_oauth(self._id).get("client_info")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._update("client_info", client_info)
_CONNECTION_ERRORS = (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream, ConnectionError)


class ToolCallError(Exception):
    """The MCP server reported the tool call as failed (``is_error``)."""


def qualified_name(slug: str, tool_name: str) -> str:
    """``<slug>__<tool>``, kept within the 64-char limit LLM APIs put on tool names."""
    name = f"{slug}__{tool_name}"
    if len(name) <= 64:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    return f"{name[:55]}_{digest}"


def result_to_dict(result: Any) -> dict[str, Any]:
    """CallToolResult -> ``{"text": ..., "data": ...}``. ``data`` is the structured or JSON payload."""
    parts = []
    for block in result.content:
        if getattr(block, "type", "") == "text":
            parts.append(block.text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')}]")
    text = "\n".join(parts)
    if result.is_error:
        raise ToolCallError(text or "The tool reported an error")
    data = result.structured_content
    if data is None:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            data = None
    output: dict[str, Any] = {"text": text}
    if data is not None:
        output["data"] = data
    return output


_RISKY_VERBS = re.compile(
    r"(^|[_\-.])(create|send|post|delete|remove|update|patch|put|write|move|archive|add|set|insert|upload|merge|close|"
    r"publish|invite|kick|ban|transfer|pay|execute|run|deploy|restart|drop)", re.IGNORECASE)
POLICIES = ("allow", "ask", "block")


_READ_LABEL = re.compile(r"^(search|query|list|get|retrieve|find|fetch|read|look up|show|count|check)" + r"\b", re.IGNORECASE)


def _label(description: str) -> str:
    """First line of a description without an "App | " prefix (e.g. Notion's "Notion | Search by title")."""
    first = (description or "").strip().split("\n")[0]
    head, sep, rest = first.partition(" | ")
    return rest if sep and len(head) <= 30 else first


def default_policy(tool_name: str, annotations: Any, description: str = "") -> str:
    """'ask' for tools that change things, 'allow' for read-only ones.

    A description starting with a read verb ("Search by title") wins: servers that wrap HTTP APIs
    often mark every POST as destructive. Then MCP hints, then verbs in the name.
    """
    if _READ_LABEL.match(_label(description)):
        return "allow"
    hint = (lambda key: annotations.get(key)) if isinstance(annotations, dict) else (lambda key: getattr(annotations, key, None))
    if annotations is not None:
        if hint("destructive_hint"):
            return "ask"
        if hint("read_only_hint"):
            return "allow"
    return "ask" if _RISKY_VERBS.search(tool_name) else "allow"


def prune_unused_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop shared definitions the tool never references. Some servers (Notion) attach the same
    ~650-token block to every tool, and the model is sent each tool's schema with every message."""
    for key in ("$defs", "definitions"):
        defs = schema.get(key)
        if not isinstance(defs, dict):
            continue
        rest = {k: v for k, v in schema.items() if k != key}
        keep: set[str] = set()
        todo: list[Any] = [rest]
        while todo:
            for name in re.findall(re.escape(f"#/{key}/") + r'([^"/]+)', json.dumps(todo.pop())):
                if name in defs and name not in keep:
                    keep.add(name)
                    todo.append(defs[name])
        schema = {**rest, key: {k: v for k, v in defs.items() if k in keep}} if keep else rest
    return schema


class MCPTool(Tool):
    def __init__(self, manager: "MCPManager", server: ServerConfig, tool: Any) -> None:
        description = tool.description or tool.name
        super().__init__(qualified_name(server.slug, tool.name), server.slug, f"[{server.name}] {description}")
        self._manager = manager
        self._remote_name = tool.name
        schema = dict(tool.input_schema or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        self._schema = prune_unused_defs(schema)
        annotations = getattr(tool, "annotations", None)
        self.policy = server.tool_policies.get(tool.name) or default_policy(tool.name, annotations, tool.description or "")
        # Display hints for the workflow builder: the server's own title and whether the tool changes data.
        self.title = getattr(tool, "title", None) or getattr(annotations, "title", None)
        self.read_only = getattr(annotations, "read_only_hint", None)
        self.destructive = getattr(annotations, "destructive_hint", None)

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self._manager.call_tool(self.app_id, self._remote_name, parameters)


@dataclass
class _Runtime:
    config: ServerConfig
    status: str = "connecting"  # connecting | needs_auth | connected | error | stopped
    error: Optional[str] = None
    tools: list[MCPTool] = field(default_factory=list)
    blocked: list[MCPTool] = field(default_factory=list)
    client: Optional[Client] = None
    task: Optional[asyncio.Task] = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    stopping: bool = False
    restart_requested: bool = False
    events: deque = field(default_factory=lambda: deque(maxlen=50))  # recent connection events, newest last
    connected_since: Optional[str] = None
    calls: int = 0
    failures: int = 0
    last_call_at: Optional[str] = None
    # Hosted-server sign-in in progress: the URL to open and the code the callback delivers.
    auth_url: Optional[str] = None
    auth_state: Optional[str] = None
    auth_future: Optional[asyncio.Future] = None
    connect_deadline: Any = None  # the asyncio.timeout() guarding the connect, paused while signing in
    refresh_task: Optional[asyncio.Task] = None

    def log(self, message: str) -> None:
        self.events.append({"at": _now(), "message": message})


class MCPManager:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._runtimes: dict[int, _Runtime] = {}

    # ---- lifecycle -----------------------------------------------------

    async def start_all(self) -> None:
        for config in list_servers():
            if config.enabled:
                self._start(config)

    async def stop_all(self) -> None:
        await asyncio.gather(*(self.stop(server_id) for server_id in list(self._runtimes)), return_exceptions=True)

    def _start(self, config: ServerConfig) -> None:
        runtime = _Runtime(config=config)
        self._runtimes[config.id] = runtime
        runtime.task = asyncio.create_task(self._run(runtime), name=f"mcp-{config.slug}")

    async def stop(self, server_id: int) -> None:
        runtime = self._runtimes.pop(server_id, None)
        if runtime is None:
            return
        runtime.stopping = True
        runtime.wake.set()
        if runtime.task:
            try:
                await asyncio.wait_for(runtime.task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                runtime.task.cancel()
            except Exception:
                logger.exception("MCP server %s stopped with an error", runtime.config.slug)
        self._unregister(runtime)

    async def apply(self, config: Optional[ServerConfig], server_id: int) -> None:
        """Bring the runtime in line with a created, updated or deleted server."""
        await self.stop(server_id)
        if config is not None and config.enabled:
            self._start(config)

    async def wait_ready(self, server_id: int, timeout: float = CONNECT_TIMEOUT) -> None:
        """Wait until a server has connected or failed (used after create/restart)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            runtime = self._runtimes.get(server_id)
            if runtime is None or runtime.status in ("connected", "error", "needs_auth"):
                return
            await asyncio.sleep(0.1)

    async def wait_all_ready(self) -> None:
        await asyncio.gather(*(self.wait_ready(server_id) for server_id in list(self._runtimes)))

    # ---- connection loop -------------------------------------------------

    def _target(self, runtime: _Runtime, stack: AsyncExitStack) -> Any:
        config = runtime.config
        if config.transport == "stdio":
            if not store.local_servers_allowed():
                raise RuntimeError("Local MCP servers are turned off: Nexus connects to hosted servers only. "
                                   "Remove this one and install the app's hosted server from the Marketplace.")
            path = log_path(config.slug)
            if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
                path.unlink()
            errlog = stack.enter_context(path.open("a", encoding="utf-8", errors="replace"))
            errlog.write(f"\n--- {_now()} starting {config.command} ---\n")
            errlog.flush()
            params = StdioServerParameters(command=config.command, args=config.args, env=config.env or None)
            return stdio_client(params, errlog=errlog)
        # Servers with their own Authorization header use it; the rest can sign in with OAuth when they ask (401).
        has_auth_header = any(key.lower() == "authorization" for key in config.headers)
        http_client = create_mcp_http_client(
            headers=config.headers or None, auth=None if has_auth_header else self._oauth(runtime),
        )
        stack.push_async_callback(http_client.aclose)
        return streamable_http_client(config.url, http_client=http_client)

    def _oauth(self, runtime: _Runtime) -> OAuthClientProvider:
        loop = asyncio.get_running_loop()

        async def redirect(authorization_url: str) -> None:
            runtime.auth_url = authorization_url
            runtime.auth_state = (parse_qs(urlparse(authorization_url).query).get("state") or [None])[0]
            runtime.auth_future = loop.create_future()
            runtime.status = "needs_auth"
            runtime.log("Waiting for you to sign in")
            if runtime.connect_deadline is not None:
                runtime.connect_deadline.reschedule(None)  # signing in may take a while

        async def callback() -> AuthorizationCodeResult:
            try:
                return await asyncio.wait_for(runtime.auth_future, SIGN_IN_TIMEOUT)
            except asyncio.TimeoutError:
                raise RuntimeError("Sign-in was not completed in time. Reconnect to try again.") from None
            finally:
                runtime.auth_url = runtime.auth_state = runtime.auth_future = None
                runtime.status = "connecting"
                if runtime.connect_deadline is not None:
                    runtime.connect_deadline.reschedule(loop.time() + CONNECT_TIMEOUT)

        return OAuthClientProvider(
            server_url=runtime.config.url,
            client_metadata=OAuthClientMetadata(
                client_name="Nexus", redirect_uris=[OAUTH_CALLBACK_URL],
                grant_types=["authorization_code", "refresh_token"], token_endpoint_auth_method="none",
            ),
            storage=_TokenStorage(runtime.config.id),
            redirect_handler=redirect,
            callback_handler=callback,
        )

    def complete_sign_in(self, state: str, code: str, iss: Optional[str] = None) -> bool:
        """Hand the authorization code from the OAuth callback to the server waiting for it. ``iss`` is the
        RFC 9207 issuer some servers (hosted Notion) send back; the SDK rejects the sign-in without it.
        Must run on the event loop (the callback route is async) so the waiting connection wakes up."""
        for runtime in self._runtimes.values():
            future = runtime.auth_future
            if runtime.auth_state and runtime.auth_state == state and future and not future.done():
                future.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss or None))
                return True
        return False

    async def _listen_for_changes(self, runtime: _Runtime, client: Client) -> None:
        """2026-07-28 servers announce tool changes on a subscription stream."""
        try:
            async with client.listen(tools_list_changed=True) as subscription:
                async for _ in subscription:
                    await self._refresh_tools(runtime)
        except ListenNotSupportedError:
            pass  # older servers send notifications/tools/list_changed instead (see _message_handler)
        except Exception as exc:  # the server may not offer subscriptions; tools still work
            logger.debug("MCP server %s: no tool-change subscription (%s)", runtime.config.slug, _describe(exc))

    def _message_handler(self, runtime: _Runtime):
        """Older servers announce tool changes as a notification."""
        async def handle(message: Any) -> None:
            if isinstance(message, mcp_types.ToolListChangedNotification):
                # Not awaited here: listing tools needs this same receive loop to deliver the reply.
                runtime.refresh_task = asyncio.get_running_loop().create_task(self._refresh_tools(runtime))
        return handle

    async def _refresh_tools(self, runtime: _Runtime) -> None:
        client = runtime.client
        if client is None:
            return
        try:
            tools = await self._list_tools(client)
        except Exception as exc:
            runtime.log(f"Could not refresh tools: {_describe(exc)}")
            return
        self._unregister(runtime)
        self._set_tools(runtime, tools)
        self._register(runtime)
        runtime.log(f"Tool list changed: {len(tools)} tool(s)")

    def _set_tools(self, runtime: _Runtime, tools: list[Any]) -> None:
        every_tool = [MCPTool(self, runtime.config, tool) for tool in tools]
        runtime.blocked = [t for t in every_tool if t.policy == "block"]
        runtime.tools = [t for t in every_tool if t.policy != "block"]

    async def _run(self, runtime: _Runtime) -> None:
        attempt = 0
        while not runtime.stopping:
            runtime.status = "connecting"
            runtime.log("Connecting")
            try:
                async with AsyncExitStack() as stack:
                    async with asyncio.timeout(CONNECT_TIMEOUT) as deadline:
                        runtime.connect_deadline = deadline
                        client = await stack.enter_async_context(Client(
                            self._target(runtime, stack), read_timeout_seconds=CALL_TIMEOUT,
                            message_handler=self._message_handler(runtime),
                        ))
                        tools = await self._list_tools(client)
                    runtime.connect_deadline = None
                    runtime.client = client
                    self._set_tools(runtime, tools)
                    self._register(runtime)
                    runtime.status, runtime.error, attempt = "connected", None, 0
                    runtime.connected_since = _now()
                    runtime.log(f"Connected with {len(tools)} tool(s)")
                    logger.info("MCP server %s connected with %d tool(s)", runtime.config.slug, len(tools))
                    listener = asyncio.create_task(self._listen_for_changes(runtime, client))
                    try:
                        if not (runtime.stopping or runtime.restart_requested):
                            runtime.wake.clear()
                            await runtime.wake.wait()  # set on stop, or when a call finds the connection broken
                    finally:
                        listener.cancel()
                        await asyncio.gather(listener, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # ExceptionGroup from the SDK's task groups included
                runtime.error = _describe(exc)
                if runtime.config.transport == "stdio" and (said := server_said(runtime.config.slug)):
                    runtime.error = f"{runtime.error}. The server said: {said}"  # e.g. "API_KEY ... is required"
                logger.warning("MCP server %s failed: %s", runtime.config.slug, runtime.error)
            finally:
                runtime.client = runtime.connect_deadline = runtime.connected_since = None
                runtime.auth_url = runtime.auth_state = runtime.auth_future = None
                self._unregister(runtime)

            if not runtime.stopping and not runtime.restart_requested:
                runtime.log(f"Failed: {runtime.error or 'Connection lost'}")
                if attempt == 0:  # once per outage, not on every retry
                    log_activity("server_error", f"MCP server '{runtime.config.name}' is not connected",
                                 runtime.error or "Connection lost", {"server": runtime.config.slug})

            if runtime.stopping:
                break
            if runtime.restart_requested:
                runtime.restart_requested, runtime.error, attempt = False, None, 0
                continue
            runtime.status = "error"
            runtime.error = runtime.error or "Connection lost"
            delay = min(5 * 2 ** attempt, MAX_BACKOFF)
            attempt += 1
            runtime.wake.clear()
            try:
                await asyncio.wait_for(runtime.wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        runtime.status = "stopped"

    @staticmethod
    async def _list_tools(client: Client) -> list[Any]:
        tools, cursor = [], None
        for _ in range(50):  # a server that paginates forever must not hang startup
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        return tools

    def _register(self, runtime: _Runtime) -> None:
        for tool in runtime.tools:
            self._registry.register(tool)

    def _unregister(self, runtime: _Runtime) -> None:
        for tool in runtime.tools:
            self._registry.unregister(tool.tool_name)

    # ---- calls & state ---------------------------------------------------

    def _runtime_for(self, slug: str) -> Optional[_Runtime]:
        return next((r for r in self._runtimes.values() if r.config.slug == slug), None)

    async def call_tool(self, slug: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime = self._runtime_for(slug)
        if runtime is None or runtime.status != "connected" or runtime.client is None:
            raise AppNotConnectedError(f"MCP server '{slug}' is not connected")
        runtime.calls += 1
        runtime.last_call_at = _now()
        try:
            result = await runtime.client.call_tool(tool_name, arguments)
            return result_to_dict(result)
        except _CONNECTION_ERRORS as exc:
            runtime.failures += 1
            runtime.wake.set()  # reconnect in the background
            raise AppNotConnectedError(f"Lost connection to MCP server '{slug}'") from exc
        except Exception:
            runtime.failures += 1
            raise

    async def check(self, server_id: int) -> dict[str, Any]:
        """A harmless live round trip: the server's who-am-I tool when it has one without required inputs
        (proves the sign-in works too), else a fresh tool listing."""
        from app.agent.abstract import BaseAgent
        from app.agent.tool_selection import WHO_AM_I_NAME, WHO_AM_I_TEXT

        runtime = self._runtimes.get(server_id)
        if runtime is None or runtime.status != "connected" or runtime.client is None:
            state = runtime.status if runtime else "stopped"
            hint = {"needs_auth": "sign in first", "connecting": "still connecting"}.get(state, runtime and runtime.error)
            return {"ok": False, "message": f"Not connected ({state})" + (f": {hint}" if hint else "")}
        probe = next((t for t in runtime.tools if not t.parameters_schema.get("required")
                      and (WHO_AM_I_NAME.search(t._remote_name) or WHO_AM_I_TEXT.search(t.description))), None)
        try:
            if probe:
                result = await self.call_tool(runtime.config.slug, probe._remote_name, {})
                return {"ok": True, "message": f"Works. Signed in as {BaseAgent._summarize_tool_result(probe.tool_name, result)}"}
            tools = await self._list_tools(runtime.client)
            return {"ok": True, "message": f"Works. The server answered with {len(tools)} tool(s)."}
        except Exception as exc:
            return {"ok": False, "message": _describe(exc)}

    def restart(self, server_id: int) -> bool:
        runtime = self._runtimes.get(server_id)
        if runtime is None:
            return False
        runtime.restart_requested = True
        runtime.status = "connecting"
        runtime.wake.set()
        return True

    def status(self, server_id: int) -> dict[str, Any]:
        runtime = self._runtimes.get(server_id)
        if runtime is None:
            return {"status": "stopped", "error": None, "tools": [], "blocked_tools": [], "auth_url": None,
                    "health": None}

        def view(t: MCPTool) -> dict[str, Any]:
            return {"name": t.tool_name, "remote_name": t._remote_name, "description": t.description, "policy": t.policy,
                    "title": t.title, "read_only": t.read_only, "destructive": t.destructive,
                    "required": list(t.parameters_schema.get("required") or [])}

        return {
            "status": runtime.status,
            "error": runtime.error,
            "tools": [view(t) for t in runtime.tools],
            "blocked_tools": [view(t) for t in runtime.blocked],
            "auth_url": runtime.auth_url,
            "health": {"connected_since": runtime.connected_since, "calls": runtime.calls,
                       "failures": runtime.failures, "last_call_at": runtime.last_call_at},
        }

    def logs(self, server_id: int, slug: str) -> dict[str, Any]:
        runtime = self._runtimes.get(server_id)
        return {"events": list(runtime.events) if runtime else [], "stderr": read_log_tail(slug)}

    def server_states(self) -> dict[str, dict[str, bool]]:
        """``{slug: {enabled, connected, available}}`` for every configured server."""
        states = {}
        for config in list_servers():
            runtime = self._runtimes.get(config.id)
            connected = bool(runtime and runtime.status == "connected")
            states[config.slug] = {"enabled": config.enabled, "connected": connected, "available": config.enabled and connected}
        return states

    def availability(self) -> dict[str, bool]:
        return {slug: state["available"] for slug, state in self.server_states().items()}


def _describe(exc: BaseException) -> str:
    """Readable message from an exception, unwrapping ExceptionGroups from task groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return f"Timed out after {CONNECT_TIMEOUT}s connecting to the server"
    if isinstance(exc, FileNotFoundError):
        return f"Command not found: {exc.filename or exc}"
    return str(exc) or exc.__class__.__name__

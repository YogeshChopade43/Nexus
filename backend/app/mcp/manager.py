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
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Optional

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.core.exceptions import AppNotConnectedError
from app.mcp.store import ServerConfig, list_servers
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 60  # first npx/uvx launch may download the package
CALL_TIMEOUT = 120
MAX_BACKOFF = 300
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


class MCPTool(Tool):
    def __init__(self, manager: "MCPManager", server: ServerConfig, tool: Any) -> None:
        description = tool.description or tool.name
        super().__init__(qualified_name(server.slug, tool.name), server.slug, f"[{server.name}] {description}")
        self._manager = manager
        self._remote_name = tool.name
        schema = dict(tool.input_schema or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        self._schema = schema

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self._manager.call_tool(self.app_id, self._remote_name, parameters)


@dataclass
class _Runtime:
    config: ServerConfig
    status: str = "connecting"  # connecting | connected | error | stopped
    error: Optional[str] = None
    tools: list[MCPTool] = field(default_factory=list)
    client: Optional[Client] = None
    task: Optional[asyncio.Task] = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    stopping: bool = False
    restart_requested: bool = False


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
            if runtime is None or runtime.status in ("connected", "error"):
                return
            await asyncio.sleep(0.1)

    # ---- connection loop -------------------------------------------------

    def _target(self, config: ServerConfig, stack: AsyncExitStack) -> Any:
        if config.transport == "stdio":
            return StdioServerParameters(command=config.command, args=config.args, env=config.env or None)
        http_client = create_mcp_http_client(headers=config.headers or None)
        stack.push_async_callback(http_client.aclose)
        return streamable_http_client(config.url, http_client=http_client)

    async def _run(self, runtime: _Runtime) -> None:
        attempt = 0
        while not runtime.stopping:
            runtime.status = "connecting"
            try:
                async with AsyncExitStack() as stack:
                    async with asyncio.timeout(CONNECT_TIMEOUT):
                        client = await stack.enter_async_context(
                            Client(self._target(runtime.config, stack), read_timeout_seconds=CALL_TIMEOUT)
                        )
                        tools = await self._list_tools(client)
                    runtime.client = client
                    runtime.tools = [MCPTool(self, runtime.config, tool) for tool in tools]
                    self._register(runtime)
                    runtime.status, runtime.error, attempt = "connected", None, 0
                    logger.info("MCP server %s connected with %d tool(s)", runtime.config.slug, len(tools))
                    if not (runtime.stopping or runtime.restart_requested):
                        runtime.wake.clear()
                        await runtime.wake.wait()  # set on stop, or when a call finds the connection broken
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # ExceptionGroup from the SDK's task groups included
                runtime.error = _describe(exc)
                logger.warning("MCP server %s failed: %s", runtime.config.slug, runtime.error)
            finally:
                runtime.client = None
                self._unregister(runtime)

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
        try:
            result = await runtime.client.call_tool(tool_name, arguments)
        except _CONNECTION_ERRORS as exc:
            runtime.wake.set()  # reconnect in the background
            raise AppNotConnectedError(f"Lost connection to MCP server '{slug}'") from exc
        return result_to_dict(result)

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
            return {"status": "stopped", "error": None, "tools": []}
        return {
            "status": runtime.status,
            "error": runtime.error,
            "tools": [
                {"name": t.tool_name, "remote_name": t._remote_name, "description": t.description}
                for t in runtime.tools
            ],
        }

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

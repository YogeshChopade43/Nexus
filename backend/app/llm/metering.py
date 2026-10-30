"""Token accounting and the daily AI limit, applied to every LLM provider Nexus creates.

``Metered`` wraps a provider: before each call it checks today's usage against the
``dailyTokenLimit`` setting, and after each call it records the tokens the API reported.
Streamed replies report no usage, so those are estimated at ~4 characters per token.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, Optional

from app.core.database import get_connection
from app.llm.errors import as_provider_error

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_RETRY_WAIT = 30.0  # seconds; a longer Retry-After is capped
_sleep = asyncio.sleep  # patched in tests


class DailyLimitReached(RuntimeError):
    pass


# Calls made while handling one chat reply, so the reply can show what it cost.
_scope: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar("llm_usage_scope", default=None)


@contextmanager
def usage_scope() -> Iterator[list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    token = _scope.set(records)
    try:
        yield records
    finally:
        _scope.reset(token)


def usage_total(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Tokens for a set of calls, and the cost when the user entered prices for every model used."""
    from app.api.routes.settings import load_user_settings

    prices = load_user_settings().get("llmPrices") or {}
    total = {"input_tokens": sum(r["input"] for r in records), "output_tokens": sum(r["output"] for r in records),
             "estimated": any(r["estimated"] for r in records), "cost": None,
             # The biggest prompt sent at once is how full the context window got (calls re-send everything so far).
             "context_tokens": max((r["input"] for r in records), default=0),
             "cached_tokens": sum(r.get("cached", 0) for r in records)}
    if records and all(isinstance(prices.get(r["model"]), dict) for r in records):
        total["cost"] = round(sum(
            (r["input"] * float(prices[r["model"]].get("input") or 0) + r["output"] * float(prices[r["model"]].get("output") or 0))
            / 1_000_000 for r in records), 6)
    return total


def _acting_user_id() -> Optional[int]:
    """Whose tokens these are: the signed-in person, or whom a background job acts for."""
    from app.core.database import _acting_user_id as acting

    return acting()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def tokens_used_today() -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM llm_usage WHERE timestamp >= ? AND user_id IS ?",
            (_today(), _acting_user_id())
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _daily_limit() -> int:
    from app.api.routes.settings import load_user_settings

    try:
        return max(0, int(load_user_settings().get("dailyTokenLimit") or 0))
    except (TypeError, ValueError):
        return 0


def check_budget() -> None:
    limit = _daily_limit()
    if limit and tokens_used_today() >= limit:
        raise DailyLimitReached(
            f"The daily AI limit of {limit:,} tokens is used up. Raise it in Settings > General; "
            "it resets at midnight UTC."
        )


def record_usage(provider_id: Optional[int], provider: str, model: str, input_tokens: int, output_tokens: int,
                 estimated: bool = False, cached: int = 0) -> None:
    scope = _scope.get()
    if scope is not None:
        scope.append({"model": model or "", "input": int(input_tokens or 0), "output": int(output_tokens or 0),
                      "estimated": estimated, "cached": int(cached or 0)})
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO llm_usage (timestamp, provider_id, provider, model, input_tokens, output_tokens, estimated, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), provider_id, provider, model or "",
             int(input_tokens or 0), int(output_tokens or 0), int(estimated), _acting_user_id()),
        )
        conn.commit()
    finally:
        conn.close()


def _usage_tokens(usage: Any) -> tuple[int, int]:
    """(input, output) from Anthropic-style or OpenAI-style usage objects. Input is the whole prompt: Anthropic
    reports the part read from or written to its cache separately."""
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    prompt += int(usage.get("cache_read_input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
    return prompt, int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)


def _cached_tokens(usage: Any) -> int:
    """Prompt tokens the provider served from its cache (cheaper and faster)."""
    if not isinstance(usage, dict):
        return 0
    details = usage.get("prompt_tokens_details") or {}
    return int(usage.get("cache_read_input_tokens") or (details.get("cached_tokens") if isinstance(details, dict) else 0) or 0)


def _estimate(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


class Metered:
    """Proxy around an LLM provider; everything else passes through unchanged."""

    def __init__(self, provider: Any, provider_id: Optional[int], config: dict[str, Any]) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._name = config.get("provider_name") or getattr(provider, "provider_name", "")
        self._model = config.get("model") or getattr(provider, "default_model", "")
        self.defaults: dict[str, Any] = {}  # per-chat options such as temperature, applied to every call

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def _record(self, result: Any, model: str) -> None:
        if isinstance(result, dict):
            input_tokens, output_tokens = _usage_tokens(result.get("usage"))
            if input_tokens or output_tokens:
                record_usage(self._provider_id, self._name, result.get("model") or model or self._model,
                             input_tokens, output_tokens, cached=_cached_tokens(result.get("usage")))

    async def _wait_before_retry(self, exc: BaseException, attempt: int) -> None:
        """Re-raise ``exc`` unless it's a passing AI-service failure with retries left; otherwise wait."""
        error = as_provider_error(exc, self._name)
        if error is None or not error.retryable or attempt >= MAX_RETRIES:
            if error is not None and error is not exc:
                raise error from exc
            raise exc
        wait = min(error.retry_after, MAX_RETRY_WAIT) if error.retry_after is not None             else 2 ** attempt * random.uniform(0.75, 1.25)
        logger.warning("%s failed (%s), retrying in %.1fs", self._name, error.status or error.detail, wait)
        await _sleep(wait)

    async def _retrying(self, call: Callable[[], Awaitable[Any]]) -> Any:
        check_budget()
        attempt = 0
        while True:
            try:
                return await call()
            except Exception as exc:
                await self._wait_before_retry(exc, attempt)
                attempt += 1

    async def chat(self, messages: Any, **kwargs: Any) -> Any:
        result = await self._retrying(lambda: self._provider.chat(messages=messages, **{**self.defaults, **kwargs}))
        self._record(result, kwargs.get("model", ""))
        return result

    async def chat_with_tools(self, messages: Any, tools: Any, **kwargs: Any) -> Any:
        result = await self._retrying(
            lambda: self._provider.chat_with_tools(messages=messages, tools=tools, **{**self.defaults, **kwargs}))
        self._record(result, kwargs.get("model", ""))
        return result

    async def chat_stream(self, messages: Any, **kwargs: Any) -> AsyncIterator[str]:
        check_budget()
        parts: list[str] = []
        attempt = 0
        try:
            while True:
                try:
                    async for chunk in self._provider.chat_stream(messages=messages, **{**self.defaults, **kwargs}):
                        parts.append(chunk)
                        yield chunk
                    break
                except Exception as exc:
                    if parts:  # part of the reply is already on screen: restarting would repeat it
                        error = as_provider_error(exc, self._name)
                        if error is not None and error is not exc:
                            raise error from exc
                        raise
                    await self._wait_before_retry(exc, attempt)
                    attempt += 1
        finally:
            record_usage(self._provider_id, self._name, kwargs.get("model") or self._model,
                         _estimate(json.dumps(messages, default=str)), _estimate("".join(parts)), estimated=True)

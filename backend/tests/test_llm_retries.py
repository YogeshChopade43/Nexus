"""Transient AI-service failures are retried inside Metered; lasting ones surface as ProviderError."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.llm import metering
from app.llm.errors import ProviderError
from app.llm.metering import Metered

CFG = {"provider_name": "anthropic", "model": "m"}


class Flaky:
    """Raises the queued exceptions in turn, then answers "ok"."""
    provider_name = "anthropic"
    default_model = "m"

    def __init__(self, errors, stream=None, fail_after_first=None):
        self.errors, self.calls, self.stream_calls = list(errors), 0, 0
        self.stream, self.fail_after_first = stream or [], fail_after_first

    async def _answer(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"content": "ok"}

    async def chat(self, messages, **kwargs):
        return await self._answer()

    async def chat_with_tools(self, messages, tools, **kwargs):
        return await self._answer()

    async def chat_stream(self, messages, **kwargs):
        self.stream_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        for index, chunk in enumerate(self.stream):
            yield chunk
            if index == 0 and self.fail_after_first:
                raise self.fail_after_first


@pytest.fixture
def waits(monkeypatch):
    seen = []

    async def sleep(seconds):
        seen.append(seconds)
    monkeypatch.setattr(metering, "_sleep", sleep)
    monkeypatch.setattr(metering, "check_budget", lambda: None)
    monkeypatch.setattr(metering, "record_usage", lambda *a, **k: None)
    return seen


def collect(stream):
    async def go():
        return [chunk async for chunk in stream]
    return asyncio.run(go())


def test_retries_a_529_then_succeeds(waits):
    flaky = Flaky([ProviderError("anthropic", 529)])
    assert asyncio.run(Metered(flaky, None, CFG).chat([{"role": "user", "content": "hi"}]))["content"] == "ok"
    assert flaky.calls == 2 and len(waits) == 1 and 0.75 <= waits[0] <= 1.25


def test_honours_retry_after_capped_at_30(waits):
    flaky = Flaky([ProviderError("anthropic", 429, retry_after=2), ProviderError("anthropic", 429, retry_after=90)])
    asyncio.run(Metered(flaky, None, CFG).chat_with_tools([], []))
    assert waits == [2, 30]


def test_gives_up_after_three_retries(waits):
    flaky = Flaky([ProviderError("anthropic", 503)] * 5)
    with pytest.raises(ProviderError):
        asyncio.run(Metered(flaky, None, CFG).chat([]))
    assert flaky.calls == 4 and len(waits) == 3


def test_401_is_not_retried(waits):
    flaky = Flaky([ProviderError("anthropic", 401)])
    with pytest.raises(ProviderError) as err:
        asyncio.run(Metered(flaky, None, CFG).chat([]))
    assert flaky.calls == 1 and "API key" in err.value.user_message()


def test_httpx_errors_are_converted_and_retried(waits):
    request = httpx.Request("POST", "https://x")
    busy = httpx.HTTPStatusError("busy", request=request,
                                 response=httpx.Response(429, request=request, headers={"retry-after": "3"}))
    flaky = Flaky([busy, httpx.ConnectTimeout("slow")])
    asyncio.run(Metered(flaky, None, {"provider_name": "openai", "model": "m"}).chat([]))
    assert flaky.calls == 3 and waits[0] == 3 and 1.5 <= waits[1] <= 2.5


def test_daily_limit_is_not_retried(monkeypatch, waits):
    def over():
        raise RuntimeError("Daily AI limit reached")
    monkeypatch.setattr(metering, "check_budget", over)
    with pytest.raises(RuntimeError, match="Daily AI limit"):
        asyncio.run(Metered(Flaky([]), None, CFG).chat([]))
    assert waits == []


def test_stream_retries_only_before_the_first_chunk(waits):
    before = Flaky([ProviderError("anthropic", 529)], stream=["a", "b"])
    assert collect(Metered(before, None, CFG).chat_stream([])) == ["a", "b"]
    after = Flaky([], stream=["a", "b"], fail_after_first=ProviderError("anthropic", 529))
    with pytest.raises(ProviderError):
        collect(Metered(after, None, CFG).chat_stream([]))
    assert after.stream_calls == 1


def test_user_messages():
    assert ProviderError("anthropic", 529).user_message() == "Anthropic is overloaded right now (HTTP 529). Try again in a minute."
    assert ProviderError("anthropic", None, "timed out").user_message() == "Couldn't reach Anthropic (timed out). Try again in a minute."
    assert ProviderError("openai", 429).user_message() == "OpenAI is rate-limiting requests right now (HTTP 429). Try again in a minute."


class _Unread(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"error": "busy"}'


def test_streamed_http_errors_are_converted_and_retried(waits):
    request = httpx.Request("POST", "https://x")
    unread = httpx.Response(429, request=request, stream=_Unread())  # body not read, as with client.stream()
    flaky = Flaky([httpx.HTTPStatusError("busy", request=request, response=unread)])
    asyncio.run(Metered(flaky, None, {"provider_name": "openai", "model": "m"}).chat([]))
    assert flaky.calls == 2 and len(waits) == 1


def test_read_timeouts_are_not_retried(waits):
    flaky = Flaky([httpx.ReadTimeout("no reply")])
    with pytest.raises(ProviderError) as err:
        asyncio.run(Metered(flaky, None, CFG).chat([]))
    assert flaky.calls == 1 and waits == [] and "timed out" in err.value.user_message()


def test_anthropic_mid_stream_overload_is_a_provider_error(monkeypatch):
    from app.llm.providers import anthropic
    sse = 'event: error\ndata: {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}\n\n'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=sse))
    client = httpx.AsyncClient
    monkeypatch.setattr(anthropic.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    with pytest.raises(ProviderError) as err:
        collect(anthropic.AnthropicProvider("key").chat_stream([{"role": "user", "content": "hi"}]))
    assert err.value.status == 529 and err.value.retryable


def test_litellm_errors_are_provider_errors(monkeypatch):
    import sys
    import types

    class RateLimitError(Exception):
        status_code = 429

    async def acompletion(**kwargs):
        raise RateLimitError("slow down")
    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(acompletion=acompletion))
    from app.llm.providers.litellm import LiteLLMProvider
    with pytest.raises(ProviderError) as err:
        asyncio.run(LiteLLMProvider().chat([{"role": "user", "content": "hi"}]))
    assert err.value.status == 429 and "rate-limiting" in err.value.user_message()

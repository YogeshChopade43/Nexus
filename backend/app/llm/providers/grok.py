from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from app.llm.base import BaseLLMProvider
from app.llm.providers._openai_compat import (
    build_chat_body,
    openai_compatible_headers,
    parse_chat_response,
    stream_chat_completions,
)

PROVIDER_NAME = "grok"


class GrokProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "grok-2"):
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "grok-2"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = "https://api.x.ai/v1/chat/completions"
        body = build_chat_body(messages, model or self._model, temperature, max_tokens)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=openai_compatible_headers(self._api_key), json=body)
            response.raise_for_status()
            data = response.json()

        return parse_chat_response(data)

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = "https://api.x.ai/v1/chat/completions"
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, tools=tools
        )

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=openai_compatible_headers(self._api_key), json=body)
            response.raise_for_status()
            data = response.json()

        return parse_chat_response(data)

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        import httpx

        url = "https://api.x.ai/v1/chat/completions"
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, stream=True
        )

        async with httpx.AsyncClient(timeout=60) as client:
            async for chunk in stream_chat_completions(
                client, url, openai_compatible_headers(self._api_key), body
            ):
                yield chunk

    def get_models(self) -> list[str]:
        return ["grok-2", "grok-2-vision", "grok-3", "grok-3-vision", "grok-3-fast"]
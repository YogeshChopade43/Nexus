from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from app.llm.base import BaseLLMProvider
from app.llm.providers._openai_compat import (
    build_chat_body,
    openai_compatible_headers,
    parse_chat_response,
    stream_chat_completions,
)

PROVIDER_NAME = "openai"


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "gpt-4o"):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = f"{self._base_url}/chat/completions"
        headers = openai_compatible_headers(self._api_key)
        body = build_chat_body(messages, model or self._model, temperature, max_tokens)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=body)
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

        url = f"{self._base_url}/chat/completions"
        headers = openai_compatible_headers(self._api_key)
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, tools=tools
        )

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, json=body)
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

        url = f"{self._base_url}/chat/completions"
        headers = openai_compatible_headers(self._api_key)
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, stream=True
        )

        async with httpx.AsyncClient(timeout=120) as client:
            async for chunk in stream_chat_completions(client, url, headers, body):
                yield chunk

    def get_models(self) -> list[str]:
        return ["gpt-4o", "gpt-4", "gpt-3.5-turbo", "gpt-4o-mini", "gpt-4-turbo"]
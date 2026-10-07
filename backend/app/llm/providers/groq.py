from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from app.llm.base import BaseLLMProvider
from app.llm.providers._openai_compat import (
    build_chat_body,
    openai_compatible_headers,
    parse_chat_response,
    stream_chat_completions,
)

PROVIDER_NAME = "groq"


class GroqProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "llama-3.3-70b-versatile"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = "https://api.groq.com/openai/v1/chat/completions"
        body = build_chat_body(messages, model or self._model, temperature, max_tokens)

        async with httpx.AsyncClient(timeout=120) as client:
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

        url = "https://api.groq.com/openai/v1/chat/completions"
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, tools=tools
        )

        async with httpx.AsyncClient(timeout=120) as client:
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

        url = "https://api.groq.com/openai/v1/chat/completions"
        body = build_chat_body(
            messages, model or self._model, temperature, max_tokens, stream=True
        )

        async with httpx.AsyncClient(timeout=120) as client:
            async for chunk in stream_chat_completions(
                client, url, openai_compatible_headers(self._api_key), body
            ):
                yield chunk

    def get_models(self) -> list[str]:
        return [
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]
from __future__ import annotations

from typing import Any, Optional

from app.llm.base import BaseLLMProvider

PROVIDER_NAME = "openrouter"


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "openai/gpt-4"):
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "openai/gpt-4"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nexus.ai",
            "X-Title": "Nexus",
        }
        body = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.7,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        choice = data.get("choices", [{}])[0]
        return {
            "content": choice.get("message", {}).get("content", ""),
            "model": data.get("model", ""),
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage", {}),
        }

    @staticmethod
    def get_models() -> list[str]:
        return [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "openai/gpt-4",
            "openai/gpt-4-turbo",
            "anthropic/claude-3-haiku",
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3-opus",
            "meta-llama/llama-3.1-8b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "meta-llama/llama-3.3-70b-versatile",
        ]

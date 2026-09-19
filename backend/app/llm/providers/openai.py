from __future__ import annotations

from typing import Any, Optional

from app.llm.base import BaseLLMProvider

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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.7,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=60) as client:
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

    def get_models(self) -> list[str]:
        return ["gpt-4o", "gpt-4", "gpt-3.5-turbo", "gpt-4o-mini", "gpt-4-turbo"]

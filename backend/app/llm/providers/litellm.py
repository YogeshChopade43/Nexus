from __future__ import annotations

from typing import Any, Optional

from app.llm.base import BaseLLMProvider

PROVIDER_NAME = "litellm"


class LiteLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "gpt-4o"):
        self._api_key = api_key
        self._base_url = base_url
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
        import litellm

        response = await litellm.acompletion(
            model=model or self._model,
            messages=messages,
            temperature=temperature if temperature is not None else 0.7,
            max_tokens=max_tokens,
            api_key=self._api_key,
            base_url=self._base_url,
        )

        choice = response.choices[0]
        usage = response.usage
        return {
            "content": choice.message.content or "",
            "model": response.model,
            "finish_reason": choice.finish_reason,
            "usage": {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": (usage.prompt_tokens + usage.completion_tokens) if usage else 0,
            },
        }

    def get_models(self) -> list[str]:
        return ["gpt-4o", "claude-3-5-sonnet-20241022", "gemini-1.5-pro", "ollama/llama3", "grok-2"]

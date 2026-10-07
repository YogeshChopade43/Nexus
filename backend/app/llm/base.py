from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional


class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        pass

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield incremental text chunks as they arrive from the provider.

        Default implementation falls back to a single ``chat`` call and yields
        the full content in one chunk, so providers that don't natively stream
        still work with SSE endpoints.
        """
        result = await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        content = result.get("content", "")
        if content:
            yield content

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider_name} does not support tool calling")

    @abstractmethod
    def get_models(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        pass

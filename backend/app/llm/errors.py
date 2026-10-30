"""One error type for AI-service failures, so retries and the chat's error message work the same for every provider."""
from __future__ import annotations

from typing import Optional

import httpx

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
NAMES = {"openai": "OpenAI", "openrouter": "OpenRouter", "huggingface": "HuggingFace", "litellm": "LiteLLM"}


class ProviderError(Exception):
    def __init__(self, provider: str, status: Optional[int], detail: str = "", retry_after: Optional[float] = None,
                 transient: bool = True) -> None:
        self.provider, self.status, self.detail, self.retry_after = provider, status, detail, retry_after
        self.transient = transient  # False: retrying would only repeat a long wait (a reply that never came)
        super().__init__(f"{provider} error {status}: {detail}" if status else f"{provider} unreachable: {detail}")

    @property
    def retryable(self) -> bool:
        return self.transient and (self.status is None or self.status in RETRYABLE)

    def user_message(self) -> str:
        name = NAMES.get(self.provider.lower(), self.provider.capitalize())
        if self.status is None:
            return f"Couldn't reach {name} ({self.detail or 'no response'}). Try again in a minute."
        if self.status == 429:
            return f"{name} is rate-limiting requests right now (HTTP 429). Try again in a minute."
        if self.status in (503, 529):
            return f"{name} is overloaded right now (HTTP {self.status}). Try again in a minute."
        if self.status in (401, 403):
            return f"{name} rejected the API key (HTTP {self.status}). Check it in Settings > AI."
        return f"{name} returned an error (HTTP {self.status}): {self.detail[:200]}"


def _seconds(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except ValueError:  # an HTTP date: not worth parsing, the normal backoff applies
        return None


def as_provider_error(exc: BaseException, provider: str) -> Optional[ProviderError]:
    """``exc`` as a ProviderError, or None when it isn't an AI-service failure (a bug, the daily limit)."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            detail = response.text[:500]
        except httpx.ResponseNotRead:  # a streamed reply fails before its body is read
            detail = ""
        return ProviderError(provider, response.status_code, detail, _seconds(response.headers.get("retry-after")))
    if isinstance(exc, httpx.ReadTimeout):  # it took the request but never answered: don't wait that long again
        return ProviderError(provider, None, "timed out", transient=False)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(provider, None, "timed out")
    if isinstance(exc, httpx.TransportError):
        return ProviderError(provider, None, "connection failed")
    return None

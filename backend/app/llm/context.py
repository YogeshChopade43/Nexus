"""How many tokens a model can take at once (its context window), for the chat's context meter.

OpenRouter publishes every model's window, so it is looked up there. Other providers have no such API,
so a short table of well-known model families is used; anything else is reported as unknown.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
CACHE_SECONDS = 6 * 3600

# Published windows by model family, most specific first (ids may carry a vendor prefix: "openai/gpt-4o").
# ponytail: a hand-kept table; replace with each provider's model API where one exists (as for OpenRouter).
# For Ollama this is the model's maximum; Ollama itself may allocate less (num_ctx).
FAMILIES: list[tuple[str, int]] = [
    (r"gpt-4\.1", 1_047_576),
    (r"gpt-5", 400_000),
    (r"gpt-4o|gpt-4-turbo|chatgpt-4o", 128_000),
    (r"(^|/)o[134](-|$)", 200_000),
    (r"gpt-4(?!\.|o|-turbo)", 8_192),
    (r"gpt-3\.5", 16_385),
    (r"claude", 200_000),
    (r"gemini-1\.5-pro", 2_097_152),
    (r"gemini", 1_048_576),
    (r"grok-4", 256_000),
    (r"grok", 131_072),
    (r"llama-?3\.[1-3]|llama-?4", 128_000),
    (r"llama-?3", 8_192),
    (r"mixtral", 32_768),
    (r"mistral-(large|medium|small)|codestral", 128_000),
    (r"deepseek", 128_000),
    (r"qwen", 32_768),
]

_cache: dict[str, Any] = {"at": 0.0, "models": {}}


def family_window(model: str) -> Optional[int]:
    name = (model or "").lower()
    return next((tokens for pattern, tokens in FAMILIES if re.search(pattern, name)), None)


async def _openrouter_models() -> dict[str, int]:
    """OpenRouter's public model list as {id: context length}, cached for a few hours."""
    if time.time() - _cache["at"] < CACHE_SECONDS and _cache["models"]:
        return _cache["models"]
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(OPENROUTER_MODELS)
        response.raise_for_status()
    models = {m["id"]: int(m["context_length"]) for m in response.json().get("data", []) if m.get("context_length")}
    _cache.update(at=time.time(), models=models)
    return models


async def context_window(provider: str, model: str) -> dict[str, Any]:
    """{"tokens": window or None, "source": where it came from ("openrouter", "model family") or None}."""
    if provider == "openrouter":
        try:
            tokens = (await _openrouter_models()).get(model)
            if tokens:
                return {"tokens": tokens, "source": "openrouter"}
        except Exception as exc:  # offline or changed API: fall back to the table
            logger.info("OpenRouter model list unavailable: %s", exc)
    tokens = family_window(model)
    return {"tokens": tokens, "source": "model family" if tokens else None}

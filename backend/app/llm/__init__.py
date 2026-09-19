from __future__ import annotations

import logging
from typing import Any

from app.llm.base import BaseLLMProvider
from app.llm.registry import LLMRegistry, _load_provider_class

logger = logging.getLogger(__name__)


def build_llm_registry() -> LLMRegistry:
    registry = LLMRegistry()
    configs = registry.list_configs()
    for config in configs:
        if not config.get("enabled", True):
            continue
        try:
            provider_class = _load_provider_class(config["provider_name"])
            kwargs = {}
            if config.get("api_key"):
                kwargs["api_key"] = config["api_key"]
            if config.get("base_url"):
                kwargs["base_url"] = config["base_url"]
            if config.get("model"):
                kwargs["model"] = config["model"]
            provider = provider_class(**kwargs)
            registry.register(provider, config)
        except Exception as exc:
            logger.warning(f"Failed to load provider {config['provider_name']}: {exc}")
    return registry

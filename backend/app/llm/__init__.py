from __future__ import annotations

from app.llm.base import BaseLLMProvider
from app.llm.registry import LLMRegistry, _load_provider_class


def build_llm_registry() -> LLMRegistry:
    """A registry that loads providers from the database on demand, keyed by row id."""
    return LLMRegistry()

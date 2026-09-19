from __future__ import annotations

import importlib
import json
import sqlite3
from typing import Any, Optional

from app.core.database import get_connection
from app.llm.base import BaseLLMProvider

PROVIDER_MAP = {
    "openai": "app.llm.providers.openai:OpenAIProvider",
    "anthropic": "app.llm.providers.anthropic:AnthropicProvider",
    "ollama": "app.llm.providers.ollama:OllamaProvider",
    "grok": "app.llm.providers.grok:GrokProvider",
    "litellm": "app.llm.providers.litellm:LiteLLMProvider",
    "huggingface": "app.llm.providers.huggingface:HuggingFaceProvider",
    "groq": "app.llm.providers.groq:GroqProvider",
    "openrouter": "app.llm.providers.openrouter:OpenRouterProvider",
}


def _load_provider_class(provider_name: str) -> type:
    path = PROVIDER_MAP.get(provider_name)
    if path is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
    module_path, class_name = path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class LLMRegistry:
    def __init__(self) -> None:
        self._providers: dict[int, BaseLLMProvider] = {}
        self._configs: dict[int, dict[str, Any]] = {}

    def register(self, provider: BaseLLMProvider, config: dict[str, Any]) -> int:
        provider_id = hash((provider.provider_name, config.get("model", ""))) & 0x7FFFFFFF
        self._providers[provider_id] = provider
        self._configs[provider_id] = config
        return provider_id

    def get_provider(self, provider_id: int) -> BaseLLMProvider:
        if provider_id not in self._providers:
            self._load_provider(provider_id)
        return self._providers[provider_id]

    def get_config(self, provider_id: int) -> dict[str, Any]:
        return self._configs.get(provider_id, {})

    def _load_provider(self, provider_id: int) -> None:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
            if row is None:
                raise ValueError(f"LLM provider not found: {provider_id}")
            config = dict(row)
            provider_class = _load_provider_class(config["provider_name"])
            kwargs = {}
            if config["api_key"]:
                kwargs["api_key"] = config["api_key"]
            if config["base_url"]:
                kwargs["base_url"] = config["base_url"]
            if config["model"]:
                kwargs["model"] = config["model"]
            provider = provider_class(**kwargs)
            self._providers[provider_id] = provider
            self._configs[provider_id] = config
        finally:
            conn.close()

    def list_configs(self) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM llm_providers ORDER BY id").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def create_config(self, provider_name: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None, enabled: bool = True) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO llm_providers (provider_name, model, api_key, base_url, enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (provider_name, model, api_key, base_url, int(enabled)),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_config(self, provider_id: int, **kwargs: Any) -> bool:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
            if row is None:
                return False

            updates = []
            values = []
            for key, value in kwargs.items():
                if key in ("model", "api_key", "base_url", "enabled"):
                    updates.append(f"{key} = ?")
                    values.append(value)

            if not updates:
                return False

            values.append(provider_id)
            conn.execute(f"UPDATE llm_providers SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()

            provider_id_in_cache = next((k for k, v in self._configs.items() if v.get("id") == provider_id), None)
            if provider_id_in_cache is not None:
                self._configs[provider_id_in_cache].update(kwargs)
                if "api_key" in kwargs or "base_url" in kwargs or "model" in kwargs:
                    del self._providers[provider_id_in_cache]
                    del self._configs[provider_id_in_cache]

            return True
        finally:
            conn.close()

    def delete_config(self, provider_id: int) -> bool:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
            conn.commit()
            for key in list(self._providers.keys()):
                if self._configs.get(key, {}).get("id") == provider_id:
                    del self._providers[key]
                    del self._configs[key]
            return True
        finally:
            conn.close()

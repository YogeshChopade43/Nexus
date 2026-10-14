from __future__ import annotations

import importlib
import inspect
from typing import Any, Optional

from app.auth.owner import owner_id
from app.core.database import get_connection
from app.core.secrets import decrypt_api_key
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
        provider_id = int(config["id"])
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
            config["api_key"] = decrypt_api_key(config.get("api_key"))
            provider_class = _load_provider_class(config["provider_name"])
            kwargs = {}
            if config["api_key"]:
                kwargs["api_key"] = config["api_key"]
            if config["base_url"] and "base_url" in inspect.signature(provider_class.__init__).parameters:
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
            rows = conn.execute("SELECT * FROM llm_providers WHERE user_id = ? ORDER BY id", (owner_id(),)).fetchall()
            results = []
            for row in rows:
                config = dict(row)
                # Never expose the stored key through the API surface.
                config["api_key"] = "***" if config.get("api_key") else None
                results.append(config)
            return results
        finally:
            conn.close()

    def create_config(self, provider_name: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None, enabled: bool = True) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO llm_providers (provider_name, model, api_key, base_url, enabled, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (provider_name, model, encrypt_api_key(api_key), base_url, int(enabled), owner_id()),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def delete_config(self, provider_id: int) -> bool:
        conn = get_connection()
        try:
            cursor = conn.execute("DELETE FROM llm_providers WHERE id = ? AND user_id = ?", (provider_id, owner_id()))
            conn.commit()
        finally:
            conn.close()
        self._providers.pop(provider_id, None)
        self._configs.pop(provider_id, None)
        return cursor.rowcount > 0

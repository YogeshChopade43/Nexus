from __future__ import annotations

from typing import Any, Optional

from app.llm.base import BaseLLMProvider

PROVIDER_NAME = "ollama"


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "llama3"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = f"{self._base_url}/api/chat"
        body = {
            "model": model or self._model,
            "messages": messages,
            "stream": False,
            "temperature": temperature if temperature is not None else 0.7,
        }
        if max_tokens is not None:
            body["num_predict"] = max_tokens

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            data = response.json()

        return {
            "content": data.get("response", ""),
            "model": data.get("model", ""),
            "finish_reason": data.get("done_reason"),
            "usage": {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
        }

    def get_models(self) -> list[str]:
        return ["llama3", "llama3.1", "mistral", "mixtral", "phi3", "gemma2", "codellama"]

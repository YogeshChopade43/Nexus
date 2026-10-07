from __future__ import annotations

from typing import Any, AsyncIterator, Optional

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
            "content": data.get("message", {}).get("content", "") or data.get("response", ""),
            "model": data.get("model", ""),
            "finish_reason": data.get("done_reason"),
            "usage": {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
        }

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        import json as _json

        import httpx

        url = f"{self._base_url}/api/chat"
        body = {
            "model": model or self._model,
            "messages": messages,
            "stream": True,
            "temperature": temperature if temperature is not None else 0.7,
        }
        if max_tokens is not None:
            body["num_predict"] = max_tokens

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        payload = _json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    message = payload.get("message", {})
                    chunk = message.get("content", "")
                    if chunk:
                        yield chunk

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
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
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ],
        }
        if max_tokens is not None:
            body["num_predict"] = max_tokens

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        tool_calls = []
        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            tool_calls.append({
                "name": func.get("name", ""),
                "arguments": func.get("arguments", {}),
            })

        return {
            "content": message.get("content", ""),
            "tool_calls": tool_calls,
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
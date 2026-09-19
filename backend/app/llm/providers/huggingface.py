from __future__ import annotations

from typing import Any, Optional

from app.llm.base import BaseLLMProvider

PROVIDER_NAME = "huggingface"


class HuggingFaceProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "meta-llama/Llama-3.1-70B-Instruct"):
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return "meta-llama/Llama-3.1-70B-Instruct"

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        url = f"https://api-inference.huggingface.co/models/{model or self._model}"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        system_message = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            elif msg.get("role") in ("user", "assistant"):
                user_messages.append(msg)

        body = {
            "inputs": f"<|system|>\n{system_message}\n<|user|>\n"
            + "\n<|assistant|>\n".join(
                msg.get("content", "") for msg in user_messages if msg.get("role") == "user"
            )
            + "\n<|assistant|>\n",
        }
        if max_tokens is not None:
            body["max_new_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        content = ""
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "generated_text" in item:
                    content += item["generated_text"]
        elif isinstance(data, dict) and "generated_text" in data:
            content = data["generated_text"]
        else:
            content = str(data)

        return {
            "content": content,
            "model": model or self._model,
            "finish_reason": "stop",
            "usage": {},
        }

    def get_models(self) -> list[str]:
        return ["meta-llama/Llama-3.1-70B-Instruct", "mistralai/Mistral-7B-Instruct", "google/gemma-2-27b-it"]

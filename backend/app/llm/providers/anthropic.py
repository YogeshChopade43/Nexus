from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from app.llm.base import BaseLLMProvider

PROVIDER_NAME = "anthropic"
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5-5"


def to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Convert OpenAI-style chat messages into Anthropic's (system, messages) shape.

    - ``system`` turns move to the top-level ``system`` field.
    - assistant ``tool_calls`` become ``tool_use`` blocks.
    - consecutive ``tool`` results are grouped into ONE user turn of ``tool_result`` blocks.
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            for call in message["tool_calls"]:
                function = call.get("function", {})
                arguments = function.get("arguments") or "{}"
                try:
                    tool_input = json.loads(arguments) if isinstance(arguments, str) else arguments
                except json.JSONDecodeError:
                    tool_input = {}
                blocks.append({"type": "tool_use", "id": call.get("id", ""), "name": function.get("name", ""), "input": tool_input or {}})
            out.append({"role": "assistant", "content": blocks})
            continue
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return "\n\n".join(system_parts), out


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}

    def _body(self, messages, model, temperature, max_tokens, **extra) -> dict[str, Any]:
        system, converted = to_anthropic_messages(messages)
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": converted,
            "max_tokens": max_tokens if max_tokens is not None else 16000,
            **extra,
        }
        if system:
            body["system"] = system
        # Current Claude models reject sampling params; only send when the caller explicitly asks.
        if temperature is not None:
            body["temperature"] = temperature
        return body

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(API_URL, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Anthropic API error {response.status_code}: {response.text[:500]}")
        return self._parse_response(response.json())

    async def chat(self, messages, model: str = "", temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None, **kwargs: Any) -> dict[str, Any]:
        return await self._post(self._body(messages, model, temperature, max_tokens))

    async def chat_stream(self, messages, model: str = "", temperature: Optional[float] = None,
                          max_tokens: Optional[int] = None, **kwargs: Any) -> AsyncIterator[str]:
        body = self._body(messages, model, temperature, max_tokens, stream=True)
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", API_URL, headers=self._headers(), json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise RuntimeError(f"Anthropic API error {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[len("data:"):].strip())
                    except ValueError:
                        continue
                    if payload.get("type") == "error":
                        raise RuntimeError(f"Anthropic stream error: {payload.get('error')}")
                    if payload.get("type") == "content_block_delta":
                        chunk = payload.get("delta", {}).get("text", "")
                        if chunk:
                            yield chunk

    async def chat_with_tools(self, messages, tools, model: str = "", temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None, **kwargs: Any) -> dict[str, Any]:
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
        return await self._post(self._body(messages, model, temperature, max_tokens, tools=anthropic_tools))

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block.get("id"), "name": block.get("name", ""), "arguments": block.get("input", {})})
        if data.get("stop_reason") == "refusal" and not content:
            content = "The model declined to respond to this request."
        usage = data.get("usage", {})
        return {
            "content": content,
            "tool_calls": tool_calls,
            "model": data.get("model", ""),
            "finish_reason": data.get("stop_reason"),
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }

    def get_models(self) -> list[str]:
        return ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1"]

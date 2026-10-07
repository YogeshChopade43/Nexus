"""Shared helpers for OpenAI-compatible streaming.

The OpenAI, Grok, Groq, Ollama and OpenRouter providers all speak the same
``data: {...}`` Server-Sent Events wire format. This module centralizes the
parsing so each provider only needs to configure the URL, headers and body.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional


def openai_compatible_headers(api_key: str, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def build_chat_body(
    messages: list[dict[str, Any]],
    model: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
    tools: Optional[list[dict[str, Any]]] = None,
    stream: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature if temperature is not None else 0.7,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]
    if stream:
        body["stream"] = True
    return body


def parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for tc in message.get("tool_calls") or []:
        if tc.get("type") == "function":
            func = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id"),
                "name": func.get("name", ""),
                "arguments": func.get("arguments", "{}"),
            })
    return tool_calls


async def stream_chat_completions(
    client: Any,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> AsyncIterator[str]:
    """Yield incremental ``content`` deltas from an OpenAI-compatible stream."""
    async with client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue
            choice = (payload.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            chunk = delta.get("content", "")
            if chunk:
                yield chunk


def parse_chat_response(data: dict[str, Any]) -> dict[str, Any]:
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    return {
        "content": message.get("content") or "",
        "tool_calls": parse_tool_calls(message),
        "model": data.get("model", ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
    }
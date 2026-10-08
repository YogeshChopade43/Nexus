from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_connection
from app.core.secrets import encrypt_api_key
from app.llm.registry import LLMRegistry, _load_provider_class, PROVIDER_MAP
from app.models.llm import (
    LLMProvider as LLMProviderModel,
    LLMCreateRequest,
    LLMUpdateRequest,
    ChatRequest,
    ChatResponse,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])

PROVIDER_LABELS = {
    "openai": "OpenAI / ChatGPT",
    "anthropic": "Anthropic / Claude",
    "ollama": "Ollama",
    "grok": "Grok (xAI)",
    "litellm": "LiteLLM",
    "huggingface": "Hugging Face",
    "groq": "Groq",
    "openrouter": "OpenRouter",
}


def _get_registry() -> LLMRegistry:
    return LLMRegistry()


def _mask_key(value: str | None) -> str | None:
    """Never return a stored API key through the HTTP API."""
    if not value:
        return None
    if value.startswith("fernet-llm:"):
        return "***"
    return "***"

@router.get("/providers")
def list_providers() -> list[dict[str, Any]]:
    results = []
    for name, label in PROVIDER_LABELS.items():
        try:
            provider_class = _load_provider_class(name)
            import inspect
            sig = inspect.signature(provider_class.__init__)
            kwargs = {}
            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                if param.default is not inspect.Parameter.empty:
                    kwargs[param_name] = param.default
                else:
                    kwargs[param_name] = ""
            instance = provider_class(**kwargs)
            models = instance.get_models()
            results.append({"name": name, "label": label, "models": models})
        except Exception:
            results.append({"name": name, "label": label, "models": []})
    return results


@router.get("/")
def list_llm_providers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    registry = _get_registry()
    configs = registry.list_configs()[offset:offset + limit]
    results = []
    for config in configs:
        config_dict = dict(config)
        config_dict["api_key"] = _mask_key(config_dict.get("api_key"))
        config_dict["label"] = PROVIDER_LABELS.get(config["provider_name"], config["provider_name"])
        results.append(config_dict)
    return results


@router.post("/")
def create_llm_provider(req: LLMCreateRequest) -> dict[str, Any]:
    if req.provider_name not in PROVIDER_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider_name}")
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="A model is required")
    if req.provider_name not in ("ollama", "litellm") and not req.api_key:
        raise HTTPException(status_code=400, detail="An API key is required for this provider")
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO llm_providers (provider_name, model, api_key, base_url, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (req.provider_name, req.model, encrypt_api_key(req.api_key), req.base_url, int(req.enabled)),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "provider_name": req.provider_name, "model": req.model}
    finally:
        conn.close()


@router.put("/{provider_id}")
def update_llm_provider(provider_id: int, req: LLMUpdateRequest) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="LLM provider not found")

        updates = []
        values = []
        if req.model is not None:
            updates.append("model = ?")
            values.append(req.model)
        if req.api_key:
            updates.append("api_key = ?")
            values.append(encrypt_api_key(req.api_key))
        if req.base_url is not None:
            updates.append("base_url = ?")
            values.append(req.base_url)
        if req.enabled is not None:
            updates.append("enabled = ?")
            values.append(int(req.enabled))

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        values.append(provider_id)
        updates.append("updated_at = datetime('now')")
        conn.execute(f"UPDATE llm_providers SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
        return {"id": provider_id, "updated": True}
    finally:
        conn.close()


@router.delete("/{provider_id}")
def delete_llm_provider(provider_id: int) -> dict[str, Any]:
    registry = _get_registry()
    if not registry.delete_config(provider_id):
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return {"id": provider_id, "deleted": True}


@router.get("/{provider_id}")
def get_llm_provider(provider_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="LLM provider not found")
        config = dict(row)
        config["api_key"] = _mask_key(config.get("api_key"))
        config["label"] = PROVIDER_LABELS.get(config["provider_name"], config["provider_name"])
        return config
    finally:
        conn.close()


@router.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    from app.llm.utils import get_active_llm_provider

    try:
        provider, config = get_active_llm_provider(
            provider_id=req.provider_id,
            provider_name=req.provider_name,
        )
    except HTTPException:
        raise

    model = req.model or config.get("model", provider.default_model)

    try:
        result = await provider.chat(
            messages=req.messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return ChatResponse(
            content=result["content"],
            model=result.get("model", model),
            provider=provider.provider_name,
            usage=result.get("usage"),
            finish_reason=result.get("finish_reason"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream chat completion tokens as Server-Sent Events."""
    import json as _json

    from fastapi.responses import StreamingResponse
    from app.llm.utils import get_active_llm_provider

    try:
        provider, config = get_active_llm_provider(
            provider_id=req.provider_id,
            provider_name=req.provider_name,
        )
    except HTTPException:
        raise

    model = req.model or config.get("model", provider.default_model)

    async def event_generator():
        try:
            async for chunk in provider.chat_stream(
                messages=req.messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                yield f"data: {_json.dumps({'delta': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

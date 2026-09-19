from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from app.core.database import get_connection
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
    from app.llm import build_llm_registry
    return build_llm_registry()


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
def list_llm_providers() -> list[dict[str, Any]]:
    registry = _get_registry()
    configs = []
    for config in registry.list_configs():
        config_dict = dict(config)
        config_dict["label"] = PROVIDER_LABELS.get(config["provider_name"], config["provider_name"])
        configs.append(config_dict)
    return configs


@router.post("/")
def create_llm_provider(req: LLMCreateRequest) -> dict[str, Any]:
    if req.provider_name not in PROVIDER_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider_name}")
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO llm_providers (provider_name, model, api_key, base_url, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (req.provider_name, req.model, req.api_key, req.base_url, int(req.enabled)),
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
        if req.api_key is not None:
            updates.append("api_key = ?")
            values.append(req.api_key)
        if req.base_url is not None:
            updates.append("base_url = ?")
            values.append(req.base_url)
        if req.enabled is not None:
            updates.append("enabled = ?")
            values.append(int(req.enabled))

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        values.append(provider_id)
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
        config["label"] = PROVIDER_LABELS.get(config["provider_name"], config["provider_name"])
        return config
    finally:
        conn.close()


@router.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    from app.llm import build_llm_registry

    registry = build_llm_registry()
    provider_id = None

    if req.provider_name:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM llm_providers WHERE provider_name = ? AND enabled = 1 ORDER BY id DESC LIMIT 1",
                (req.provider_name,),
            ).fetchone()
            if row:
                provider_id = row["id"]
        finally:
            conn.close()

    if provider_id is None:
        configs = registry.list_configs()
        enabled = [c for c in configs if c.get("enabled", True)]
        if enabled:
            provider_id = enabled[0]["id"]

    if provider_id is None:
        raise HTTPException(status_code=400, detail="No LLM provider configured")

    provider = registry.get_provider(provider_id)
    config = registry.get_config(provider_id)
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

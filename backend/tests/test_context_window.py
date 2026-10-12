"""How full a chat's context window is: the largest prompt of the last reply, against the model's window."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.llm import context
from app.llm.metering import usage_total
from app.main import app


def test_usage_reports_the_largest_single_prompt_as_context(client):
    records = [{"model": "m", "input": 900, "output": 10, "estimated": False},
               {"model": "m", "input": 1500, "output": 40, "estimated": False}]  # the second call re-sends the first's result
    total = usage_total(records)
    assert total["input_tokens"] == 2400 and total["context_tokens"] == 1500


def test_known_model_families_have_their_published_window():
    assert context.family_window("gpt-4o-mini") == 128_000
    assert context.family_window("openai/gpt-4.1-mini") == 1_047_576
    assert context.family_window("claude-3-5-sonnet-20241022") == 200_000
    assert context.family_window("llama-3.3-70b-versatile") == 128_000
    assert context.family_window("my-custom-finetune") is None


def test_openrouter_windows_come_from_its_model_list(monkeypatch):
    async def models():
        return {"openai/gpt-4o-mini": 128_000, "some/new-model": 262_144}

    monkeypatch.setattr(context, "_openrouter_models", models)
    assert asyncio.run(context.context_window("openrouter", "some/new-model")) == {"tokens": 262_144, "source": "openrouter"}
    assert asyncio.run(context.context_window("openai", "gpt-4o")) == {"tokens": 128_000, "source": "model family"}
    assert asyncio.run(context.context_window("openai", "mystery")) == {"tokens": None, "source": None}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_context_window_route(client):
    created = client.post("/api/llm/", json={"provider_name": "openai", "model": "gpt-4o-mini", "api_key": "k"}).json()
    try:
        r = client.get("/api/llm/context-window", params={"provider_id": created["id"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"tokens": 128_000, "source": "model family", "model": "gpt-4o-mini"}
    finally:
        client.delete(f"/api/llm/{created['id']}")

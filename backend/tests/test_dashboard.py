"""Section 9: token metering, the daily AI limit and the run dashboard."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_connection
from app.llm.metering import DailyLimitReached, Metered, tokens_used_today
from app.main import app

from tests.test_workflow_features import compose, create, run


class FakeProvider:
    provider_name = "fake"
    default_model = "fake-1"

    async def chat(self, messages, **kwargs):
        return {"content": "hi", "model": "fake-1", "usage": {"prompt_tokens": 100, "completion_tokens": 20}}

    async def chat_with_tools(self, messages, tools, **kwargs):
        return {"content": "", "tool_calls": [], "usage": {"input_tokens": 50, "output_tokens": 5}}

    async def chat_stream(self, messages, **kwargs):
        for part in ("abcd" * 10, "efgh" * 10):
            yield part


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        conn = get_connection()
        conn.execute("DELETE FROM llm_usage")
        conn.commit()
        conn.close()
        yield c


def test_usage_is_recorded_and_daily_limit_enforced(client):
    metered = Metered(FakeProvider(), 7, {"provider_name": "fake", "model": "fake-1"})
    assert metered.provider_name == "fake"  # other attributes pass through

    async def calls():
        await metered.chat(messages=[{"role": "user", "content": "x"}])
        await metered.chat_with_tools(messages=[], tools=[])
        return "".join([c async for c in metered.chat_stream(messages=[{"role": "user", "content": "y" * 40}])])

    assert len(asyncio.run(calls())) == 80
    used = tokens_used_today()
    assert used >= 120 + 55 + 20  # reported usage plus the estimate for the streamed reply
    client.patch("/api/settings/user", json={"dailyTokenLimit": used})
    try:
        with pytest.raises(DailyLimitReached, match="daily AI limit"):
            asyncio.run(metered.chat(messages=[]))
    finally:
        client.patch("/api/settings/user", json={"dailyTokenLimit": 0})
    asyncio.run(metered.chat(messages=[]))  # 0 = no limit


def test_dashboard_numbers(client):
    wf = create(client, [compose("a", "x")], name="dash ok")
    run(client, wf["id"])
    bad = create(client, [{"id": "boom", "type": "code", "config": {"code": "throw new Error('no')"}}], name="dash bad")
    run(client, bad["id"])
    client.patch("/api/settings/user", json={"llmPrices": {"fake-1": {"input": 3, "output": 15}}})

    data = client.get("/api/dashboard", params={"days": 7}).json()
    assert len(data["runs_per_day"]) == 7
    today = data["runs_per_day"][-1]
    assert today["completed"] >= 1 and today["failed"] >= 1
    assert data["failed_runs"] >= 1 and 0 < data["failure_rate"] <= 1
    assert any(f["name"] == "dash bad" for f in data["top_failing"])
    assert any(s["workflow"] == "dash ok" for s in data["slowest_steps"])
    model = next(m for m in data["tokens_by_model"] if m["model"] == "fake-1")
    assert model["cost"] == round((model["input"] * 3 + model["output"] * 15) / 1_000_000, 4)
    assert data["tokens_per_day"][-1]["input"] > 0 and data["tokens_today"] > 0

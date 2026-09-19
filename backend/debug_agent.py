import asyncio
import json
import traceback

from app.core.database import get_connection, init_db, get_app_states
from app.tools import build_tool_registry
from app.llm.registry import LLMRegistry
from app.agent.provider import DefaultAgentProvider

init_db()
conn = get_connection()
providers = conn.execute("SELECT * FROM llm_providers").fetchall()
print("LLM providers:", [dict(p) for p in providers])
states = get_app_states(conn)
print("App states:", states)
conn.close()

async def test():
    agent = DefaultAgentProvider.create_agent(
        build_tool_registry(),
        {k: v["available"] for k, v in states.items()}
    )
    registry = LLMRegistry()

    for p in providers:
        try:
            provider = registry.get_provider(p["id"])
            print(f"Provider loaded: {provider.provider_name}, model={provider.default_model}")
            result = await provider.chat(messages=[{"role": "user", "content": "Hii"}])
            content = result.get("content", "")
            print(f"LLM chat result: {content[:200]}")
        except Exception as e:
            print(f"LLM error for provider {p['id']}: {e}")
            traceback.print_exc()
        break

    for p in providers:
        try:
            provider = registry.get_provider(p["id"])
            result = await agent.run(
                task="Hii",
                context=None,
                available_tools=[],
                llm_provider=provider,
            )
            print(f"Agent run result:")
            print(json.dumps(result, indent=2, default=str)[:800])
        except Exception as e:
            print(f"Agent run error: {e}")
            traceback.print_exc()

asyncio.run(test())

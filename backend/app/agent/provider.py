from __future__ import annotations

from typing import Any, Optional

from app.agent.abstract import Agent, BaseAgent
from app.tools.registry import ToolRegistry


class DefaultAgentProvider:
    @staticmethod
    def create_agent(tool_registry: ToolRegistry, app_connections: dict[str, bool] = None) -> Agent:
        return BaseAgent(tool_registry=tool_registry, app_connections=app_connections)


class Provider:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register_agent(self, name: str, agent: Agent) -> None:
        self._agents[name] = agent

    def get_agent(self, name: str = "default") -> Agent:
        return self._agents.get(name) or self._agents.get("default") or BaseAgent(ToolRegistry())
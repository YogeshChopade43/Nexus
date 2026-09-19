from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.linear import LinearConnector


class LinearListProjectsTool(Tool):
    def __init__(self):
        super().__init__("linear_list_projects", "linear", "List Linear projects")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = LinearConnector(config)
        connector.validate_config()
        return await connector.list_projects(parameters)


class LinearCreateIssueTool(Tool):
    def __init__(self):
        super().__init__("linear_create_issue", "linear", "Create a Linear issue")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = LinearConnector(config)
        connector.validate_config()
        return await connector.create_issue(parameters)


class LinearGetIssueTool(Tool):
    def __init__(self):
        super().__init__("linear_get_issue", "linear", "Get Linear issue details")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = LinearConnector(config)
        connector.validate_config()
        return await connector.get_issue(parameters)


class LinearListIssuesTool(Tool):
    def __init__(self):
        super().__init__("linear_list_issues", "linear", "List Linear issues")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = LinearConnector(config)
        connector.validate_config()
        return await connector.list_issues(parameters)

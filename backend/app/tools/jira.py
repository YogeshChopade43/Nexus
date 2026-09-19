from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.jira import JiraConnector


class JiraListProjectsTool(Tool):
    def __init__(self):
        super().__init__("jira_list_projects", "jira", "List Jira projects")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = JiraConnector(config)
        connector.validate_config()
        return await connector.list_projects(parameters)


class JiraCreateIssueTool(Tool):
    def __init__(self):
        super().__init__("jira_create_issue", "jira", "Create a Jira issue")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = JiraConnector(config)
        connector.validate_config()
        return await connector.create_issue(parameters)


class JiraGetIssueTool(Tool):
    def __init__(self):
        super().__init__("jira_get_issue", "jira", "Get Jira issue details")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = JiraConnector(config)
        connector.validate_config()
        return await connector.get_issue(parameters)


class JiraUpdateIssueTool(Tool):
    def __init__(self):
        super().__init__("jira_update_issue", "jira", "Update a Jira issue")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = JiraConnector(config)
        connector.validate_config()
        return await connector.update_issue(parameters)

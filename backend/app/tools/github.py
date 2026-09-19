from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.github import GitHubConnector


class GitHubListRepositoriesTool(Tool):
    def __init__(self):
        super().__init__("github_list_repositories", "github", "List GitHub repositories")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GitHubConnector(config)
        connector.validate_config()
        return await connector.list_repositories(parameters)


class GitHubCreatePullRequestTool(Tool):
    def __init__(self):
        super().__init__("github_create_pull_request", "github", "Create a pull request")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GitHubConnector(config)
        connector.validate_config()
        return await connector.create_pull_request(parameters)


class GitHubListPullRequestsTool(Tool):
    def __init__(self):
        super().__init__("github_list_pull_requests", "github", "List pull requests")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GitHubConnector(config)
        connector.validate_config()
        return await connector.list_pull_requests(parameters)


class GitHubGetIssueTool(Tool):
    def __init__(self):
        super().__init__("github_get_issue", "github", "Get issue details")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GitHubConnector(config)
        connector.validate_config()
        return await connector.get_issue(parameters)


class GitHubListIssuesTool(Tool):
    def __init__(self):
        super().__init__("github_list_issues", "github", "List GitHub issues")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GitHubConnector(config)
        connector.validate_config()
        return await connector.list_issues(parameters)

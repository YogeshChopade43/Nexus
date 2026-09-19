from __future__ import annotations

from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from app.tools.github import (
    GitHubListRepositoriesTool,
    GitHubCreatePullRequestTool,
    GitHubListPullRequestsTool,
    GitHubGetIssueTool,
    GitHubListIssuesTool,
)
from app.tools.slack import (
    SlackSendMessageTool,
    SlackListChannelsTool,
    SlackCreateChannelTool,
    SlackGetUserProfileTool,
)
from app.tools.grafana import (
    GrafanaGetDashboardTool,
    GrafanaListDashboardsTool,
    GrafanaCreateAlertTool,
    GrafanaGetAlertsTool,
    GrafanaQueryLogsTool,
    GrafanaQueryMetricsTool,
    GrafanaGetAnnotationsTool,
)
from app.tools.jira import (
    JiraListProjectsTool,
    JiraCreateIssueTool,
    JiraGetIssueTool,
    JiraUpdateIssueTool,
)
from app.tools.linear import (
    LinearListProjectsTool,
    LinearCreateIssueTool,
    LinearGetIssueTool,
    LinearListIssuesTool,
)
from app.tools.notion import (
    NotionListPagesTool,
    NotionCreatePageTool,
    NotionGetPageTool,
    NotionSearchPagesTool,
)


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    tools: list[Tool] = [
        GitHubListRepositoriesTool(),
        GitHubCreatePullRequestTool(),
        GitHubListPullRequestsTool(),
        GitHubGetIssueTool(),
        GitHubListIssuesTool(),
        SlackSendMessageTool(),
        SlackListChannelsTool(),
        SlackCreateChannelTool(),
        SlackGetUserProfileTool(),
        GrafanaGetDashboardTool(),
        GrafanaListDashboardsTool(),
        GrafanaCreateAlertTool(),
        GrafanaGetAlertsTool(),
        GrafanaQueryLogsTool(),
        GrafanaQueryMetricsTool(),
        GrafanaGetAnnotationsTool(),
        JiraListProjectsTool(),
        JiraCreateIssueTool(),
        JiraGetIssueTool(),
        JiraUpdateIssueTool(),
        LinearListProjectsTool(),
        LinearCreateIssueTool(),
        LinearGetIssueTool(),
        LinearListIssuesTool(),
        NotionListPagesTool(),
        NotionCreatePageTool(),
        NotionGetPageTool(),
        NotionSearchPagesTool(),
    ]
    for tool in tools:
        registry.register(tool)
    return registry

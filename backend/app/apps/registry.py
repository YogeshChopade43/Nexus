from __future__ import annotations

from typing import Any, Dict, List


class AppCapability:
    def __init__(self, app_id: str, name: str, description: str = ""):
        self.app_id = app_id
        self.name = name
        self.description = description


APPS_REGISTRY: List[Dict[str, Any]] = [
    {
        "app_id": "github",
        "name": "GitHub",
        "description": "Code repository management, pull requests, and issue tracking",
        "category": "code",
        "icon": "/logos/github.svg",
        "enabled": True,
        "capabilities": [
            "list_repositories",
            "create_pull_request",
            "list_pull_requests",
            "get_issue",
            "list_issues",
        ],
    },
    {
        "app_id": "slack",
        "name": "Slack",
        "description": "Team messaging and collaboration",
        "category": "communication",
        "icon": "/logos/slack.svg",
        "enabled": True,
        "capabilities": [
            "send_message",
            "list_channels",
            "create_channel",
            "get_user_profile",
        ],
    },
    {
        "app_id": "grafana",
        "name": "Grafana",
        "description": "Monitoring dashboards and observability",
        "category": "monitoring",
        "icon": "/logos/grafana.svg",
        "enabled": True,
        "capabilities": [
            "get_dashboard",
            "list_dashboards",
            "create_alert",
            "get_alerts",
            "query_logs",
            "query_metrics",
            "get_annotations",
        ],
    },
    {
        "app_id": "jira",
        "name": "Jira",
        "description": "Project management and issue tracking",
        "category": "productivity",
        "icon": "/logos/jira.svg",
        "enabled": True,
        "capabilities": [
            "list_projects",
            "create_issue",
            "get_issue",
            "update_issue",
        ],
    },
    {
        "app_id": "linear",
        "name": "Linear",
        "description": "Issue tracking and project management for software teams",
        "category": "productivity",
        "icon": "/logos/linear.svg",
        "enabled": True,
        "capabilities": [
            "list_projects",
            "create_issue",
            "get_issue",
            "list_issues",
        ],
    },
    {
        "app_id": "notion",
        "name": "Notion",
        "description": "Documentation and knowledge management",
        "category": "productivity",
        "icon": "/logos/notion.svg",
        "enabled": True,
        "capabilities": [
            "list_pages",
            "create_page",
            "get_page",
            "search_pages",
        ],
    },
]

TOOLS_REGISTRY: List[Dict[str, Any]] = [
    {"tool_name": "github_list_repositories", "app_id": "github", "description": "List GitHub repositories"},
    {"tool_name": "github_create_pull_request", "app_id": "github", "description": "Create a pull request"},
    {"tool_name": "github_list_pull_requests", "app_id": "github", "description": "List pull requests"},
    {"tool_name": "github_get_issue", "app_id": "github", "description": "Get issue details"},
    {"tool_name": "github_list_issues", "app_id": "github", "description": "List GitHub issues"},
    {"tool_name": "slack_send_message", "app_id": "slack", "description": "Send a message to a channel"},
    {"tool_name": "slack_list_channels", "app_id": "slack", "description": "List Slack channels"},
    {"tool_name": "slack_create_channel", "app_id": "slack", "description": "Create a Slack channel"},
    {"tool_name": "slack_get_user_profile", "app_id": "slack", "description": "Get user profile"},
    {"tool_name": "grafana_get_dashboard", "app_id": "grafana", "description": "Get dashboard data"},
    {"tool_name": "grafana_list_dashboards", "app_id": "grafana", "description": "List dashboards"},
    {"tool_name": "grafana_create_alert", "app_id": "grafana", "description": "Create an alert"},
    {"tool_name": "grafana_get_annotations", "app_id": "grafana", "description": "Get dashboard annotations"},
    {"tool_name": "grafana_get_alerts", "app_id": "grafana", "description": "Get active alerts"},
    {"tool_name": "grafana_query_logs", "app_id": "grafana", "description": "Query logs"},
    {"tool_name": "grafana_query_metrics", "app_id": "grafana", "description": "Query metrics"},
    {"tool_name": "jira_list_projects", "app_id": "jira", "description": "List Jira projects"},
    {"tool_name": "jira_create_issue", "app_id": "jira", "description": "Create a Jira issue"},
    {"tool_name": "jira_get_issue", "app_id": "jira", "description": "Get Jira issue details"},
    {"tool_name": "jira_update_issue", "app_id": "jira", "description": "Update a Jira issue"},
    {"tool_name": "linear_list_projects", "app_id": "linear", "description": "List Linear projects"},
    {"tool_name": "linear_create_issue", "app_id": "linear", "description": "Create a Linear issue"},
    {"tool_name": "linear_get_issue", "app_id": "linear", "description": "Get Linear issue details"},
    {"tool_name": "linear_list_issues", "app_id": "linear", "description": "List Linear issues"},
    {"tool_name": "notion_list_pages", "app_id": "notion", "description": "List Notion pages"},
    {"tool_name": "notion_create_page", "app_id": "notion", "description": "Create a Notion page"},
    {"tool_name": "notion_get_page", "app_id": "notion", "description": "Get Notion page content"},
    {"tool_name": "notion_search_pages", "app_id": "notion", "description": "Search Notion pages"},
]

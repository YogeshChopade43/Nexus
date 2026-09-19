from __future__ import annotations

from typing import Any, Optional

from app.connectors.base import BaseConnector
from app.connectors.github import GitHubConnector
from app.connectors.grafana import GrafanaConnector
from app.connectors.jira import JiraConnector
from app.connectors.linear import LinearConnector
from app.connectors.notion import NotionConnector
from app.connectors.slack import SlackConnector


CONNECTOR_TYPES = {
    "github": GitHubConnector,
    "slack": SlackConnector,
    "grafana": GrafanaConnector,
    "jira": JiraConnector,
    "linear": LinearConnector,
    "notion": NotionConnector,
}


def get_connector(app_id: str, config: Optional[dict[str, Any]] = None) -> BaseConnector:
    connector_type = CONNECTOR_TYPES.get(app_id)
    if connector_type is None:
        raise KeyError("Unknown connector app_id: {}".format(app_id))
    return connector_type(config or {})


def validate_connection_config(app_id: str, config: dict[str, Any]) -> None:
    get_connector(app_id, config).validate_config()

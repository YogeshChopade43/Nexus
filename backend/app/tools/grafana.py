from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.grafana import GrafanaConnector


class GrafanaGetDashboardTool(Tool):
    def __init__(self):
        super().__init__("grafana_get_dashboard", "grafana", "Get dashboard data")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.get_dashboard(parameters)


class GrafanaListDashboardsTool(Tool):
    def __init__(self):
        super().__init__("grafana_list_dashboards", "grafana", "List dashboards")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.list_dashboards(parameters)


class GrafanaCreateAlertTool(Tool):
    def __init__(self):
        super().__init__("grafana_create_alert", "grafana", "Create an alert")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.create_alert(parameters)


class GrafanaGetAlertsTool(Tool):
    def __init__(self):
        super().__init__("grafana_get_alerts", "grafana", "Get active alerts")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.get_alerts(parameters)


class GrafanaQueryLogsTool(Tool):
    def __init__(self):
        super().__init__("grafana_query_logs", "grafana", "Query logs")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.query_logs(parameters)


class GrafanaQueryMetricsTool(Tool):
    def __init__(self):
        super().__init__("grafana_query_metrics", "grafana", "Query metrics")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.query_metrics(parameters)


class GrafanaGetAnnotationsTool(Tool):
    def __init__(self):
        super().__init__("grafana_get_annotations", "grafana", "Get dashboard annotations")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = GrafanaConnector(config)
        connector.validate_config()
        return await connector.get_annotations(parameters)

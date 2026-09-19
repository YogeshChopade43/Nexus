from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector


class GrafanaConnector(BaseConnector):
    app_id = "grafana"
    required_config = ("url", "token")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('token', '')}", "Content-Type": "application/json"}

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        return await self._request("GET", self._url(str(self.config["url"]), "api/health"), headers=self._headers())

    async def get_dashboard(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        if parameters.get("uid"):
            path = "api/dashboards/uid/{}".format(parameters["uid"])
        else:
            self._require(parameters, "dashboard_id")
            path = "api/dashboards/id/{}".format(parameters["dashboard_id"])
        data = await self._request("GET", self._url(str(self.config["url"]), path), headers=self._headers())
        return {"dashboard": data.get("dashboard", data) if isinstance(data, dict) else data}

    async def list_dashboards(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        params = {key: parameters[key] for key in ("query", "tag", "type", "dashboardIds", "folderIds", "limit") if parameters.get(key) is not None}
        params["type"] = params.get("type", "dash-db")
        data = await self._request("GET", self._url(str(self.config["url"]), "api/search"), headers=self._headers(), params=params)
        return {"dashboards": data if isinstance(data, list) else []}

    async def create_alert(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        rule = parameters.get("rule")
        if not isinstance(rule, dict):
            self._require(parameters, "name")
            rule = {"name": parameters["name"], "condition": parameters.get("condition", "A"), "data": parameters.get("data", []), "folderUid": parameters.get("folder_uid"), "noDataState": parameters.get("no_data_state", "NoData"), "execErrState": parameters.get("exec_err_state", "Error"), "for": parameters.get("for", ""), "labels": parameters.get("labels", {}), "annotations": parameters.get("annotations", {})}
        data = await self._request("POST", self._url(str(self.config["url"]), "api/v1/provisioning/alert-rules"), headers=self._headers(), json=rule)
        return {"alert": data}

    async def get_alerts(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        data = await self._request("GET", self._url(str(self.config["url"]), "api/v1/provisioning/alert-rules"), headers=self._headers())
        return {"alerts": data if isinstance(data, list) else []}

    async def query_logs(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "datasource_uid", "query")
        path = "api/datasources/proxy/uid/{}/loki/api/v1/query_range".format(parameters["datasource_uid"])
        params = {"query": parameters["query"]}
        for key in ("start", "end", "direction", "limit"):
            if parameters.get(key) is not None:
                params[key] = parameters[key]
        data = await self._request("GET", self._url(str(self.config["url"]), path), headers=self._headers(), params=params)
        return {"logs": data}

    async def query_metrics(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "datasource_uid", "query")
        path = "api/datasources/proxy/uid/{}/api/v1/query_range".format(parameters["datasource_uid"])
        params = {"query": parameters["query"]}
        for key in ("start", "end", "step", "timeout"):
            if parameters.get(key) is not None:
                params[key] = parameters[key]
        data = await self._request("GET", self._url(str(self.config["url"]), path), headers=self._headers(), params=params)
        return {"metrics": data}

    async def get_annotations(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        params = {key: parameters[key] for key in ("dashboardId", "dashboardUID", "panelId", "tags", "from", "to", "limit") if parameters.get(key) is not None}
        data = await self._request("GET", self._url(str(self.config["url"]), "api/annotations"), headers=self._headers(), params=params)
        return {"annotations": data if isinstance(data, list) else []}

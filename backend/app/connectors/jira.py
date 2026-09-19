from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import BaseConnector


class JiraConnector(BaseConnector):
    app_id = "jira"
    required_config = ("url", "email", "api_token")

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(str(self.config["email"]), str(self.config["api_token"]))

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        return await self._request("GET", self._url(str(self.config["url"]), "rest/api/3/myself"), headers=self._headers(), auth=self._auth())

    async def list_projects(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        params = {key: parameters[key] for key in ("recent", "project_keys", "project_name_query", "insight", "expand") if parameters.get(key) is not None}
        data = await self._request("GET", self._url(str(self.config["url"]), "rest/api/3/project/search"), headers=self._headers(), params=params, auth=self._auth())
        return {"projects": data.get("values", data) if isinstance(data, dict) else []}

    async def create_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        fields = parameters.get("fields")
        if not isinstance(fields, dict):
            self._require(parameters, "project", "summary", "issue_type")
            fields = {"project": {"key": parameters["project"]}, "summary": parameters["summary"], "issuetype": {"name": parameters["issue_type"]}}
            if parameters.get("description") is not None:
                fields["description"] = parameters["description"]
        data = await self._request("POST", self._url(str(self.config["url"]), "rest/api/3/issue"), headers=self._headers(), json={"fields": fields}, auth=self._auth())
        return {"issue": data}

    async def get_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "issue_id")
        params = {key: parameters[key] for key in ("fields", "expand", "properties") if parameters.get(key) is not None}
        data = await self._request("GET", self._url(str(self.config["url"]), "rest/api/3/issue/{}".format(parameters["issue_id"])), headers=self._headers(), params=params, auth=self._auth())
        return {"issue": data}

    async def update_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "issue_id")
        fields = parameters.get("fields")
        if not isinstance(fields, dict):
            fields = {key: parameters[key] for key in ("summary", "description", "status", "assignee", "priority", "labels") if parameters.get(key) is not None}
        data = await self._request("PUT", self._url(str(self.config["url"]), "rest/api/3/issue/{}".format(parameters["issue_id"])), headers=self._headers(), json={"fields": fields}, auth=self._auth())
        return {"issue": data or {"id": parameters["issue_id"], "updated": True}}

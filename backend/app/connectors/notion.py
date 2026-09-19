from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector


class NotionConnector(BaseConnector):
    app_id = "notion"
    required_config = ("token",)
    version = "2022-06-28"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('token', '')}", "Notion-Version": self.version, "Content-Type": "application/json"}

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        return await self._request("POST", self._url("https://api.notion.com/v1/", "search"), headers=self._headers(), json={"page_size": 1})

    async def list_pages(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        body = {"filter": {"property": "object", "value": "page"}, "page_size": parameters.get("page_size", 100)}
        if parameters.get("start_cursor"):
            body["start_cursor"] = parameters["start_cursor"]
        data = await self._request("POST", self._url("https://api.notion.com/v1/", "search"), headers=self._headers(), json=body)
        return {"pages": data.get("results", []) if isinstance(data, dict) else []}

    async def create_page(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "parent", "properties")
        body = {"parent": parameters["parent"], "properties": parameters["properties"]}
        if parameters.get("children") is not None:
            body["children"] = parameters["children"]
        if parameters.get("icon") is not None:
            body["icon"] = parameters["icon"]
        if parameters.get("cover") is not None:
            body["cover"] = parameters["cover"]
        data = await self._request("POST", self._url("https://api.notion.com/v1/", "pages"), headers=self._headers(), json=body)
        return {"page": data}

    async def get_page(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "page_id")
        page = await self._request("GET", self._url("https://api.notion.com/v1/", "pages/{}".format(parameters["page_id"])), headers=self._headers())
        children = await self._request("GET", self._url("https://api.notion.com/v1/", "blocks/{}/children".format(parameters["page_id"])), headers=self._headers())
        return {"page": page, "content": children.get("results", []) if isinstance(children, dict) else []}

    async def search_pages(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        body: dict[str, Any] = {"page_size": parameters.get("page_size", 100)}
        if parameters.get("query") is not None:
            body["query"] = parameters["query"]
        if parameters.get("filter") is not None:
            body["filter"] = parameters["filter"]
        data = await self._request("POST", self._url("https://api.notion.com/v1/", "search"), headers=self._headers(), json=body)
        return {"results": data.get("results", []) if isinstance(data, dict) else []}

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from app.connectors.base import BaseConnector


class GitHubConnector(BaseConnector):
    app_id = "github"
    required_config = ("token",)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.get('token', '')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Nexus",
        }

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        return await self._request("GET", self._url("https://api.github.com/", "user"), headers=self._headers())

    async def list_repositories(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        owner = parameters.get("owner") or self.config.get("owner")
        org = parameters.get("org") or self.config.get("org")
        repositories = parameters.get("repositories")
        if repositories:
            if not owner:
                from app.connectors.base import ConnectorConfigError
                raise ConnectorConfigError("Missing required parameters: owner")
            items = []
            for repository in repositories:
                path = "repos/{}/{}".format(quote(str(owner), safe=""), quote(str(repository), safe=""))
                items.append(await self._request("GET", self._url("https://api.github.com/", path), headers=self._headers()))
            return {"repositories": items}
        if org:
            path = "orgs/{}/repos".format(quote(str(org), safe=""))
        elif owner:
            path = "users/{}/repos".format(quote(str(owner), safe=""))
        else:
            path = "user/repos"
        params = {key: parameters[key] for key in ("type", "sort", "direction", "per_page", "page") if parameters.get(key) is not None}
        data = await self._request("GET", self._url("https://api.github.com/", path), headers=self._headers(), params=params)
        return {"repositories": data if isinstance(data, list) else []}

    async def create_pull_request(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "owner", "repo", "title", "head", "base")
        body = {
            "title": parameters["title"],
            "head": parameters["head"],
            "base": parameters["base"],
        }
        for key in ("body", "draft", "maintainer_can_modify"):
            if parameters.get(key) is not None:
                body[key] = parameters[key]
        path = "repos/{}/{}\n/pulls".format(quote(str(parameters["owner"]), safe=""), quote(str(parameters["repo"]), safe="")).replace("\\n/", "/")
        data = await self._request("POST", self._url("https://api.github.com/", path), headers=self._headers(), json=body)
        return {"pull_request": data}

    async def list_pull_requests(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "owner", "repo")
        path = "repos/{}/{}\n/pulls".format(quote(str(parameters["owner"]), safe=""), quote(str(parameters["repo"]), safe="")).replace("\\n/", "/")
        params = {key: parameters[key] for key in ("state", "head", "base", "sort", "direction", "per_page", "page") if parameters.get(key) is not None}
        data = await self._request("GET", self._url("https://api.github.com/", path), headers=self._headers(), params=params)
        return {"pull_requests": data if isinstance(data, list) else []}

    async def get_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "owner", "repo", "issue_number")
        path = "repos/{}/{}/issues/{}".format(
            quote(str(parameters["owner"]), safe=""),
            quote(str(parameters["repo"]), safe=""),
            quote(str(parameters["issue_number"]), safe=""),
        )
        data = await self._request("GET", self._url("https://api.github.com/", path), headers=self._headers())
        return {"issue": data}

    async def list_issues(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "owner", "repo")
        path = "repos/{}/{}\n/issues".format(quote(str(parameters["owner"]), safe=""), quote(str(parameters["repo"]), safe="")).replace("\\n/", "/")
        params = {key: parameters[key] for key in ("state", "assignee", "creator", "mentioned", "labels", "since", "sort", "direction", "per_page", "page") if parameters.get(key) is not None}
        data = await self._request("GET", self._url("https://api.github.com/", path), headers=self._headers(), params=params)
        return {"issues": data if isinstance(data, list) else []}

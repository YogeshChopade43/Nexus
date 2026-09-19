from __future__ import annotations

from typing import Any, Optional

from app.connectors.base import BaseConnector


class LinearConnector(BaseConnector):
    app_id = "linear"
    required_config = ("api_key",)
    endpoint = "https://api.linear.app/graphql"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('api_key', '')}", "Content-Type": "application/json"}

    async def _graphql(self, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.validate_config()
        data = await self._request("POST", self.config.get("endpoint", self.endpoint), headers=self._headers(), json={"query": query, "variables": variables or {}})
        if isinstance(data, dict) and data.get("errors"):
            from app.connectors.base import ConnectorRequestError
            raise ConnectorRequestError("Linear GraphQL request failed")
        return data.get("data", {}) if isinstance(data, dict) else {}

    async def validate(self) -> dict[str, Any]:
        return await self._graphql("query Viewer { viewer { id name } }")

    async def list_projects(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = "query Teams { teams { nodes { id name key } } }"
        data = await self._graphql(query)
        return {"projects": data.get("teams", {}).get("nodes", [])}

    async def create_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        from app.connectors.base import ConnectorConfigError
        self._require(parameters, "team_id", "title")
        query = "mutation IssueCreate($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier title state { name } } } }"
        input_data = {"teamId": parameters["team_id"], "title": parameters["title"]}
        for key in ("description", "priority", "assigneeId", "projectId"):
            if parameters.get(key) is not None:
                input_data[key] = parameters[key]
        data = await self._graphql(query, {"input": input_data})
        result = data.get("issueCreate", {})
        if not result.get("success"):
            raise ConnectorConfigError("Linear did not create the issue")
        return {"issue": result.get("issue", {})}

    async def get_issue(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self._require(parameters, "id")
        query = "query Issue($id: String!) { issue(id: $id) { id identifier title description state { name } assignee { name } } }"
        data = await self._graphql(query, {"id": parameters["id"]})
        return {"issue": data.get("issue", {})}

    async def list_issues(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = "query Issues($teamId: String, $first: Int) { issues(filter: { team: { id: { eq: $teamId } } }, first: $first) { nodes { id identifier title state { name } } } }"
        data = await self._graphql(query, {"teamId": parameters.get("team_id"), "first": parameters.get("first", 50)})
        return {"issues": data.get("issues", {}).get("nodes", [])}

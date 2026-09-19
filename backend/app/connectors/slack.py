from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector


class SlackConnector(BaseConnector):
    app_id = "slack"
    required_config = ("bot_token",)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('bot_token', '')}"}

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        data = await self._request("POST", self._url("https://slack.com/api/", "auth.test"), headers=self._headers(), json={})
        if isinstance(data, dict) and data.get("ok") is False:
            from app.connectors.base import ConnectorAuthError
            raise ConnectorAuthError(f"slack authentication failed: {data.get('error', 'invalid_auth')}")
        return data

    async def send_message(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "channel", "text")
        data = await self._request("POST", self._url("https://slack.com/api/", "chat.postMessage"), headers=self._headers(), json={"channel": parameters["channel"], "text": parameters["text"]})
        return {"message": data}

    async def list_channels(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        body = {key: parameters[key] for key in ("types", "limit", "cursor", "exclude_archived") if parameters.get(key) is not None}
        data = await self._request("POST", self._url("https://slack.com/api/", "conversations.list"), headers=self._headers(), json=body)
        return {"channels": data.get("channels", []) if isinstance(data, dict) else []}

    async def create_channel(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "name")
        body = {"name": parameters["name"]}
        if parameters.get("is_private") is not None:
            body["is_private"] = bool(parameters["is_private"])
        data = await self._request("POST", self._url("https://slack.com/api/", "conversations.create"), headers=self._headers(), json=body)
        return {"channel": data.get("channel", data) if isinstance(data, dict) else data}

    async def get_user_profile(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.validate_config()
        self._require(parameters, "user_id")
        data = await self._request("POST", self._url("https://slack.com/api/", "users.info"), headers=self._headers(), json={"user": parameters["user_id"]})
        return {"user": data.get("user", data) if isinstance(data, dict) else data}

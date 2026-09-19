from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.slack import SlackConnector


class SlackSendMessageTool(Tool):
    def __init__(self):
        super().__init__("slack_send_message", "slack", "Send a message to a channel")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = SlackConnector(config)
        connector.validate_config()
        return await connector.send_message(parameters)


class SlackListChannelsTool(Tool):
    def __init__(self):
        super().__init__("slack_list_channels", "slack", "List Slack channels")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = SlackConnector(config)
        connector.validate_config()
        return await connector.list_channels(parameters)


class SlackCreateChannelTool(Tool):
    def __init__(self):
        super().__init__("slack_create_channel", "slack", "Create a Slack channel")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = SlackConnector(config)
        connector.validate_config()
        return await connector.create_channel(parameters)


class SlackGetUserProfileTool(Tool):
    def __init__(self):
        super().__init__("slack_get_user_profile", "slack", "Get user profile")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = SlackConnector(config)
        connector.validate_config()
        return await connector.get_user_profile(parameters)

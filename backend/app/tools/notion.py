from __future__ import annotations

from typing import Any

from app.tools.base import Tool
from app.connectors.notion import NotionConnector


class NotionListPagesTool(Tool):
    def __init__(self):
        super().__init__("notion_list_pages", "notion", "List Notion pages")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = NotionConnector(config)
        connector.validate_config()
        return await connector.list_pages(parameters)


class NotionCreatePageTool(Tool):
    def __init__(self):
        super().__init__("notion_create_page", "notion", "Create a Notion page")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = NotionConnector(config)
        connector.validate_config()
        return await connector.create_page(parameters)


class NotionGetPageTool(Tool):
    def __init__(self):
        super().__init__("notion_get_page", "notion", "Get Notion page content")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = NotionConnector(config)
        connector.validate_config()
        return await connector.get_page(parameters)


class NotionSearchPagesTool(Tool):
    def __init__(self):
        super().__init__("notion_search_pages", "notion", "Search Notion pages")

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        config = self._get_connection_config(self.app_id)
        connector = NotionConnector(config)
        connector.validate_config()
        return await connector.search_pages(parameters)

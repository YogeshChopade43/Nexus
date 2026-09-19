from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin

import httpx


class ConnectorError(Exception):
    """Base error for connector operations."""


class ConnectorConfigError(ConnectorError):
    pass


class ConnectorAuthError(ConnectorError):
    pass


class ConnectorRequestError(ConnectorError):
    pass


class BaseConnector:
    app_id = ""
    required_config: tuple[str, ...] = ()

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = dict(config or {})

    def validate_config(self) -> None:
        missing = [key for key in self.required_config if not str(self.config.get(key, "")).strip()]
        if missing:
            raise ConnectorConfigError(
                f"{self.app_id} connector is missing required configuration: {', '.join(missing)}"
            )
        base_url = self.config.get("url") or self.config.get("base_url")
        if base_url:
            parsed = httpx.URL(str(base_url))
            if parsed.scheme not in ("http", "https") or not parsed.host:
                raise ConnectorConfigError(f"{self.app_id} connector URL must be an absolute HTTP URL")

    async def validate(self) -> dict[str, Any]:
        self.validate_config()
        return {"configured": True}

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
        auth: Any = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    auth=auth,
                )
        except httpx.RequestError as exc:
            raise ConnectorRequestError(f"{self.app_id} request failed: {exc.__class__.__name__}") from exc

        if response.status_code in (401, 403):
            raise ConnectorAuthError(f"{self.app_id} authentication failed")
        if response.status_code >= 400:
            raise ConnectorRequestError(
                f"{self.app_id} request failed with HTTP {response.status_code}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorRequestError(f"{self.app_id} returned an invalid response") from exc

    def _base_url(self, default: str) -> str:
        value = str(self.config.get("url") or self.config.get("base_url") or default).rstrip("/")
        return value + "/"

    def _url(self, default_base: str, path: str) -> str:
        return urljoin(self._base_url(default_base), path.lstrip("/"))

    @staticmethod
    def _require(parameters: dict[str, Any], *names: str) -> None:
        missing = [name for name in names if parameters.get(name) in (None, "")]
        if missing:
            raise ConnectorConfigError(f"Missing required parameters: {', '.join(missing)}")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc)
        for fragment in ("token", "secret", "password", "api_key", "apikey", "credential", "private_key"):
            if fragment in message.lower():
                return f"Connector request failed ({exc.__class__.__name__})"
        return message

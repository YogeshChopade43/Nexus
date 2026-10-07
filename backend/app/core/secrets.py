from __future__ import annotations

import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "authorization",
)


def _fernet() -> Fernet:
    raw_key = os.getenv("NEXUS_SECRET_KEY")
    if not raw_key:
        raise ValueError("NEXUS_SECRET_KEY is required to store connector credentials")
    digest = __import__("hashlib").sha256(raw_key.encode("utf-8")).digest()
    return Fernet(__import__("base64").urlsafe_b64encode(digest))


def encrypt_config(config: dict[str, Any]) -> str:
    if not config:
        return "{}"
    payload = json.dumps(config, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "fernet:" + _fernet().encrypt(payload).decode("ascii")


def decrypt_config(value: str) -> dict[str, Any]:
    if not value or value == "{}":
        return {}
    if not value.startswith("fernet:"):
        if os.getenv("NEXUS_ALLOW_PLAINTEXT_CONFIG", "false").lower() == "true" and value.lstrip().startswith("{"):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        raise ValueError("Connector configuration is encrypted and cannot be read without NEXUS_SECRET_KEY")
    try:
        payload = _fernet().decrypt(value[len("fernet:"):])
    except InvalidToken as exc:
        raise ValueError(
            "This secret was saved with a different NEXUS_SECRET_KEY. Restore the original key, "
            "or re-enter the secret in Nexus."
        ) from exc
    parsed = json.loads(payload.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "***" if any(fragment in str(key).lower() for fragment in _SENSITIVE_FRAGMENTS) else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(config)


LLM_KEY_PREFIX = "fernet-llm:"


def encrypt_api_key(value: str | None) -> str | None:
    """Encrypt a plaintext LLM API key for at-rest storage.

    Returns ``None`` for ``None``, an empty string for an empty value, and an
    already-encrypted value unchanged (idempotent). Raises ``ValueError`` when
    ``NEXUS_SECRET_KEY`` is not configured.
    """
    if value is None:
        return None
    if not value:
        return ""
    if value.startswith(LLM_KEY_PREFIX):
        return value
    payload = value.encode("utf-8")
    return LLM_KEY_PREFIX + _fernet().encrypt(payload).decode("ascii")


def decrypt_api_key(value: str | None) -> str | None:
    """Reverse :func:`encrypt_api_key`.

    Legacy plaintext values (written before this fix) are returned unchanged so
    existing databases keep working during the migration window. Raises
    ``ValueError`` when the value is encrypted but cannot be decrypted.
    """
    if value is None:
        return None
    if not value:
        return ""
    if not value.startswith(LLM_KEY_PREFIX):
        return value
    try:
        payload = _fernet().decrypt(value[len(LLM_KEY_PREFIX):])
    except InvalidToken as exc:
        raise ValueError(
            "This LLM API key was saved with a different NEXUS_SECRET_KEY. Restore the original key, "
            "or delete this provider in Settings > AI and add it again with your API key."
        ) from exc
    return payload.decode("utf-8")

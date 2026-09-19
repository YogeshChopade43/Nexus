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
        raise ValueError("Connector configuration could not be decrypted") from exc
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

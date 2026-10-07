from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "nexus.db"))
if not Path(DATABASE_PATH).is_absolute():
    # Relative paths in .env are relative to the backend directory, not the launch directory.
    DATABASE_PATH = str(BASE_DIR / DATABASE_PATH)
    os.environ["DATABASE_PATH"] = DATABASE_PATH
# Localhost by default: the API can launch MCP server commands and has no login.
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
CORS_ORIGINS: List[str] = [
    origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()
]
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
RATE_LIMIT: str = os.getenv("RATE_LIMIT", "300/minute")


def _has_encrypted_data(database_path: str) -> bool:
    """True when the database already holds secrets encrypted with some earlier key."""
    if not Path(database_path).exists():
        return False
    import sqlite3

    conn = sqlite3.connect(database_path)
    try:
        checks = (
            "SELECT 1 FROM llm_providers WHERE api_key LIKE 'fernet-llm:%' LIMIT 1",
            "SELECT 1 FROM mcp_servers WHERE env LIKE 'fernet:%' OR headers LIKE 'fernet:%' LIMIT 1",
            "SELECT 1 FROM connections WHERE config LIKE 'fernet:%' LIMIT 1",
        )
        for query in checks:
            try:
                if conn.execute(query).fetchone():
                    return True
            except sqlite3.OperationalError:
                continue  # table not present in this database
        return False
    finally:
        conn.close()


def ensure_secret_key(database_path: str = DATABASE_PATH, environ=os.environ) -> None:
    """Outside production, create and persist a NEXUS_SECRET_KEY when none is configured.

    The key lives next to the database so encrypted credentials stay readable across
    restarts. A new key is only generated for a database with no encrypted secrets:
    generating one for existing data would make every stored credential unreadable.
    """
    if environ.get("NEXUS_SECRET_KEY") or ENVIRONMENT == "production":
        return
    key_file = Path(database_path).parent / ".nexus_secret_key"
    if key_file.exists():
        environ["NEXUS_SECRET_KEY"] = key_file.read_text(encoding="utf-8").strip()
        return
    if _has_encrypted_data(database_path):
        raise SystemExit(
            "NEXUS_SECRET_KEY is not set, but the database contains credentials encrypted with it. "
            "Set the original key in backend/.env (NEXUS_SECRET_KEY=...). If it is lost, set any new key "
            "and re-enter your LLM API keys in Settings > AI and MCP server secrets on the MCP Servers page."
        )
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    key_file.write_text(key, encoding="utf-8")
    logging.getLogger(__name__).warning(
        "NEXUS_SECRET_KEY not set; generated one at %s. Back it up or set it in .env.", key_file
    )
    environ["NEXUS_SECRET_KEY"] = key


ensure_secret_key()

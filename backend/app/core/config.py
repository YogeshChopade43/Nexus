from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "nexus.db"))
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
CORS_ORIGINS: List[str] = [
    origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()
]
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
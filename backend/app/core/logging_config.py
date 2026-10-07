from __future__ import annotations

import logging
import sys

from app.core.config import LOG_LEVEL


def configure_logging() -> None:
    """Configure structured logging for the application."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.handlers.extend(handlers)
    root.setLevel(level)

    # Quiet noisy libraries
    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
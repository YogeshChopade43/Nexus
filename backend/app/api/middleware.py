from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import ENVIRONMENT, RATE_LIMIT

logger = logging.getLogger("nexus")


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI app."""

    # --- Rate limiting ---
    limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # --- Request / response logging ---
    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.perf_counter()
        response: Optional[Response] = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = response.status_code if response else "error"
            logger.info(
                "%s %s -> %s (%.1fms) [req=%s]",
                request.method,
                request.url.path,
                status,
                elapsed_ms,
                request_id,
            )

    # --- Error handling ---
    @app.middleware("http")
    async def error_handling(request: Request, call_next: Any) -> Any:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": getattr(request.state, "request_id", "")},
            )


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
    )


def validate_cors_origins() -> None:
    """Validate CORS origins are proper URLs and reject wildcards in production."""
    from app.core.config import CORS_ORIGINS

    if ENVIRONMENT == "production":
        for origin in CORS_ORIGINS:
            if origin == "*":
                raise ValueError(
                    "CORS wildcard '*' is not allowed in production. "
                    "Set explicit origins via CORS_ORIGINS environment variable."
                )
            if not origin.startswith(("http://", "https://")):
                raise ValueError(
                    f"CORS origin '{origin}' must be an absolute HTTP(S) URL."
                )

from __future__ import annotations

import logging
import os
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


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_API = ("/api/auth/", "/api/webhooks/", "/api/integrations/google/callback")
# Called by other services, with their own token or signature (and no browser involved).
GUARD_EXEMPT = ("/api/webhooks/", "/api/integrations/google/callback")


def _host_name(host_header: str) -> str:
    """The name in a Host header, without its port: "[::1]:8000" -> "::1", "localhost:8000" -> "localhost"."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _known_host(name: str) -> bool:
    """One of Nexus's own names. Any IP address is fine: DNS rebinding needs a domain name the attacker controls,
    so only names are checked (localhost, plus NEXUS_ALLOWED_HOSTS for a hostname you serve Nexus under)."""
    import ipaddress

    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    extra = {h.strip().lower() for h in os.getenv("NEXUS_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return name in {"localhost", *extra}


def _foreign_origin(request: Request) -> Optional[str]:
    """Another website behind this change (a form or fetch from its page), if any; None when it's Nexus or a script."""
    from app.core.config import CORS_ORIGINS

    origin = request.headers.get("origin")
    if origin is not None:
        own = f"{request.url.scheme}://{request.headers.get('host', '')}"
        return None if origin in CORS_ORIGINS or origin == own else origin
    if request.headers.get("sec-fetch-site") == "cross-site":  # browsers say so even when they leave Origin out
        return "another website"
    return None


def is_local(request: Request) -> bool:
    """From this machine. NEXUS_TRUSTED_NETWORKS (e.g. Docker's 172.16.0.0/12) counts as this machine too."""
    import ipaddress

    host = request.client.host if request.client else ""
    if host in LOCAL_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    networks = [n.strip() for n in os.getenv("NEXUS_TRUSTED_NETWORKS", "").split(",") if n.strip()]
    return any(address in ipaddress.ip_network(n, strict=False) for n in networks)


def require_local(request: Request, message: str) -> None:
    """Refuse requests that don't come from the machine running Nexus."""
    from fastapi import HTTPException

    if not is_local(request):
        raise HTTPException(status_code=403, detail=message)


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI app."""

    # --- Signed in: every API call acts for one person (the cookie's session) ---
    # Open without a session: signing in itself, and callbacks that carry their own check (webhook tokens, OAuth state).
    @app.middleware("http")
    async def signed_in_only(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if not path.startswith("/api/") or path.startswith(PUBLIC_API):
            return await call_next(request)
        from app.auth.context import current_user
        from app.auth.store import user_for_session

        user = user_for_session(request.cookies.get("nexus_session"))
        if user is None:
            return JSONResponse(status_code=401, content={"detail": "Sign in to use Nexus"})
        from app.auth.store import needs_verification

        if needs_verification(user):
            return JSONResponse(status_code=403, content={"detail": "Verify your email", "code": "verify_email"})
        token = current_user.set(user)
        try:
            return await call_next(request)
        finally:
            current_user.reset(token)

    # --- Other websites: DNS rebinding and forged requests ---
    # No login, on localhost: a page elsewhere must neither pose as Nexus's own server (a domain of theirs pointed
    # at 127.0.0.1) nor make changes here (a form posting to localhost). Reading is limited by CORS already.
    @app.middleware("http")
    async def same_site_only(request: Request, call_next: Any) -> Any:
        name = _host_name(request.headers.get("host", ""))
        if not _known_host(name):
            return JSONResponse(status_code=421, content={"detail": (
                f"Nexus doesn't answer to \"{name}\". If you serve it under that name, add it to NEXUS_ALLOWED_HOSTS.")})
        if request.method in UNSAFE_METHODS and not request.url.path.startswith(GUARD_EXEMPT):
            if foreign := _foreign_origin(request):
                logger.warning("Refused %s %s from %s", request.method, request.url.path, foreign)
                return JSONResponse(status_code=403, content={"detail": f"Changes from {foreign} aren't allowed."})
        return await call_next(request)

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

    # --- Security headers (outermost here, so refusals and errors carry them too) ---
    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.scheme == "https":  # behind a TLS proxy: uvicorn --proxy-headers makes this https
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


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

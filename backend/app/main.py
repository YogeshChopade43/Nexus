from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS, HOST, PORT
from app.core.database import init_db, migrate_llm_api_keys
from app.core.logging_config import configure_logging
from app.api.routes import (
    activity_router,
    agent_router,
    dashboard_router,
    knowledge_router,
    rag_router,
    marketplace_router,
    integrations_router,
    briefing_router,
    run_once_router,
    auth_router,
    auth_google_router,
    account_router,
    admin_router,
    files_router,
    mcp_router,
    health_router,
    llm_router,
    settings_router,
    tools_router,
    webhooks_router,
    workflows_router,
)
from app.api.middleware import setup_middleware, validate_cors_origins
from app.integrations import browser, integration_manager
from app.mcp import mcp_manager, server_availability
from app.tools import get_tool_registry
from app.workflows.engine import mark_interrupted_runs, resume_interrupted_runs
from app.workflows.scheduler import start_scheduler, stop_scheduler
from app.mcp import registry

configure_logging()
logger = logging.getLogger("nexus")


def validate_environment() -> None:
    """Exit with a clear message when critical configuration is missing.

    Outside production a key is generated automatically (see ``core.config``).
    """
    if not os.getenv("NEXUS_SECRET_KEY"):
        print(
            "ERROR: NEXUS_SECRET_KEY is required in production. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _ensure_rag_tables()
    from app.rag.ingest import worker as rag_worker

    rag_worker.start()
    _import_legacy_documents()
    migrate_llm_api_keys()
    interrupted = mark_interrupted_runs()
    # Servers connect in the background; startup doesn't wait for slow npx/uvx launches.
    await mcp_manager.start_all()
    integration_manager.load_all()  # built-in integrations' tools (email, calendar feeds, RSS...)
    start_scheduler()
    registry.backfill_flags()
    registry.sync_if_stale()  # Marketplace listings: background, never blocks startup
    resuming = None
    if interrupted and os.getenv("NEXUS_RESUME_RUNS", "true").lower() != "false":
        resuming = asyncio.create_task(_resume(interrupted))
    try:
        yield
    finally:
        if resuming:
            resuming.cancel()
        await rag_worker.stop()
        await registry.stop_sync()
        stop_scheduler()
        await browser.close_all()  # an open browser would keep Nexus from exiting
        await mcp_manager.stop_all()


def _ensure_rag_tables() -> None:
    from app.rag import store

    conn = store.connect()
    try:
        store.ensure_vector_table(conn)
    finally:
        conn.close()


def _import_legacy_documents() -> None:
    from app.rag.legacy import import_legacy_documents

    try:
        import_legacy_documents()
    except Exception:  # never block startup; the legacy tables stay for the next attempt
        logger.exception("Importing documents from the old knowledge base failed")


async def _resume(runs: list) -> None:
    await mcp_manager.wait_all_ready()  # the runs' tools come from MCP servers
    await resume_interrupted_runs(runs, get_tool_registry(), server_availability)


def setup_error_reports() -> bool:
    """Send unexpected errors to Sentry when SENTRY_DSN is set; nothing is sent otherwise.
    Never personal data: no cookies, IPs or emails, and no request bodies (sign-in carries passwords)."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, send_default_pii=False, max_request_body_size="never", traces_sample_rate=0.0,
                    environment=os.getenv("ENVIRONMENT", "development"))
    return True


def create_app() -> FastAPI:
    validate_environment()
    validate_cors_origins()
    setup_error_reports()

    app = FastAPI(title="Nexus Backend", version="0.2.0", lifespan=lifespan)
    setup_middleware(app)
    # Added last so it is outermost: error and rate-limit responses also carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from fastapi.responses import JSONResponse

    from app.quota import StorageFull

    app.add_exception_handler(StorageFull, lambda request, exc: JSONResponse(status_code=413, content={"detail": str(exc)}))

    for router in (
        health_router,
        dashboard_router,
        knowledge_router,
        rag_router,
        marketplace_router,
        integrations_router,
        briefing_router,
        run_once_router,
        auth_router,
        auth_google_router,
        account_router,
        admin_router,
        files_router,
        mcp_router,
        agent_router,
        workflows_router,
        tools_router,
        llm_router,
        settings_router,
        activity_router,
        webhooks_router,
    ):
        app.include_router(router)
    _serve_frontend(app)
    return app


def _serve_frontend(app: FastAPI) -> None:
    """With NEXUS_STATIC_DIR set (the Docker image), serve the built frontend from this same server."""
    static_dir = os.getenv("NEXUS_STATIC_DIR")
    if not static_dir or not os.path.isdir(static_dir):
        return
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse, RedirectResponse, Response

    root = Path(static_dir).resolve()
    # The app's own scripts only; inline styles (React) and Google Fonts; pictures from anywhere (chat answers);
    # previews of files in frames from this server; no plugins; framed by no other site.
    policy = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self'; "
              "frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path == "health":
            return RedirectResponse("/health/")
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root) and file != root / "index.html":
            return FileResponse(file)
        return FileResponse(root / "index.html", headers={"Content-Security-Policy": policy})  # client-side routes too


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)

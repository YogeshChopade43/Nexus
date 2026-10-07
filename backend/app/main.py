from __future__ import annotations

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
    mcp_router,
    health_router,
    llm_router,
    settings_router,
    tools_router,
    webhooks_router,
    workflows_router,
)
from app.api.middleware import setup_middleware, validate_cors_origins
from app.mcp import mcp_manager
from app.workflows.engine import mark_interrupted_runs
from app.workflows.scheduler import start_scheduler, stop_scheduler

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
    migrate_llm_api_keys()
    mark_interrupted_runs()
    # Servers connect in the background; startup doesn't wait for slow npx/uvx launches.
    await mcp_manager.start_all()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        await mcp_manager.stop_all()


def create_app() -> FastAPI:
    validate_environment()
    validate_cors_origins()

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

    for router in (
        health_router,
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
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)

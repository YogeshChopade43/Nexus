from __future__ import annotations

from app.api.routes.health import router as health_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.agent import router as agent_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.tools import router as tools_router
from app.api.routes.llm import router as llm_router
from app.api.routes.settings import router as settings_router
from app.api.routes.activity import router as activity_router
from app.api.routes.webhooks import router as webhooks_router

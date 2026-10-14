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
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.rag import router as rag_router
from app.api.routes.marketplace import router as marketplace_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.briefing import router as briefing_router
from app.api.routes.run_once import router as run_once_router
from app.files import router as files_router

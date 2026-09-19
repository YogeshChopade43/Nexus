from __future__ import annotations

from app.api.routes.health import router as health_router
from app.api.routes.apps import router as apps_router
from app.api.routes.agent import router as agent_router
from app.api.routes.workflows import router as workflows_router
from app.api.routes.tools import router as tools_router
from app.api.routes.llm import router as llm_router
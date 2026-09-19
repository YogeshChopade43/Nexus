from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import HOST, PORT, CORS_ORIGINS, LOG_LEVEL
from app.core.database import init_db
from app.apps import seed_apps_if_empty
from app.api.routes import health_router, apps_router, agent_router, workflows_router, tools_router, llm_router


def create_app() -> FastAPI:
    app = FastAPI(title="Nexus Backend V0", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(apps_router)
    app.include_router(agent_router)
    app.include_router(workflows_router)
    app.include_router(tools_router)
    app.include_router(llm_router)

    return app


app = create_app()

init_db()
seed_apps_if_empty()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
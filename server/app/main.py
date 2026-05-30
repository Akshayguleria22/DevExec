import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.events import router as events_router
from app.api.routes.agents import router as agents_router
from app.api.routes.sandboxes import router as sandboxes_router
from app.api.routes.projects import router as projects_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.webhook import router as webhook_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.schema_updates import apply_schema_updates
from app.core.database import SessionLocal
from app.services.agent_service import ensure_default_agents

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure all model metadata is imported before table creation.
    import app.models.deployment_event  # noqa: F401
    import app.models.execution_history  # noqa: F401
    import app.models.execution_event  # noqa: F401
    import app.models.processed_webhook  # noqa: F401
    import app.models.task  # noqa: F401
    import app.models.tool_metrics  # noqa: F401
    import app.models.project_context  # noqa: F401
    import app.models.runtime_session  # noqa: F401
    import app.models.execution_task  # noqa: F401
    import app.models.execution_artifact  # noqa: F401
    import app.models.tool_invocation  # noqa: F401
    import app.models.session_event  # noqa: F401
    import app.models.agent  # noqa: F401
    import app.models.agent_execution  # noqa: F401
    import app.models.agent_memory  # noqa: F401
    import app.models.tool_permission  # noqa: F401
    import app.models.agent_execution_event  # noqa: F401
    import app.models.execution_workspace  # noqa: F401
    import app.models.sandbox_session  # noqa: F401
    import app.models.runtime_snapshot  # noqa: F401
    import app.models.tool_execution  # noqa: F401
    import app.models.artifact  # noqa: F401

    Base.metadata.create_all(bind=engine)
    apply_schema_updates(engine)
    session = SessionLocal()
    try:
        ensure_default_agents(session)
    finally:
        session.close()
    logger.info(
        "Database tables created/verified (tasks, execution_history, tool_metrics, deployment_events, execution_events, processed_webhooks)."
    )
    yield


def create_application() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(tasks_router)
    app.include_router(webhook_router)
    app.include_router(events_router)
    app.include_router(projects_router)
    app.include_router(sessions_router)
    app.include_router(agents_router)
    app.include_router(sandboxes_router)

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_application()

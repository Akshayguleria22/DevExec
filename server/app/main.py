import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.events import router as events_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.webhook import router as webhook_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.schema_updates import apply_schema_updates

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

    Base.metadata.create_all(bind=engine)
    apply_schema_updates(engine)
    logger.info(
        "Database tables created/verified (tasks, execution_history, tool_metrics, deployment_events, execution_events, processed_webhooks)."
    )
    yield


def create_application() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(tasks_router)
    app.include_router(webhook_router)
    app.include_router(events_router)

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_application()

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.services import agent_service
from app.services.agent_event_stream import publish_agent_event
from app.services.agent_runtime import run_agent_execution

logger = logging.getLogger(__name__)


def process_agent_execution(execution_id: str) -> None:
    db = SessionLocal()
    execution = None

    try:
        exec_uuid = UUID(execution_id)
        execution = agent_service.get_execution(db, exec_uuid)
        if execution is None:
            logger.warning("Agent execution %s not found.", execution_id)
            return

        agent = agent_service.get_agent(db, execution.agent_id)
        if agent is None:
            logger.warning("Agent %s not found for execution %s.", execution.agent_id, execution_id)
            return

        allowed_tools = agent_service.get_allowed_tools(db, agent.id)
        if not allowed_tools and agent.agent_type != "coordinator":
            publish_agent_event(
                db,
                execution.id,
                "execution_failed",
                {"error": "No tools permitted for this agent."},
            )
            agent_service.update_execution(
                db,
                execution,
                {"status": "failed", "error": "No tools permitted for this agent."},
            )
            return

        run_agent_execution(db, agent, execution, allowed_tools)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent execution %s failed.", execution_id)
        if execution is not None:
            agent_service.update_execution(
                db,
                execution,
                {"status": "failed", "error": str(exc)},
            )
            publish_agent_event(
                db,
                execution.id,
                "execution_failed",
                {"error": str(exc)},
            )
        raise
    finally:
        db.close()

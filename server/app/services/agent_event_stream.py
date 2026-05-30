import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.redis import redis_connection
from app.models.agent_execution_event import AgentExecutionEvent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_agent_event_channel(execution_id: str) -> str:
    return f"agent_events:{execution_id}"


def _serialize_event(event: AgentExecutionEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "execution_id": str(event.execution_id),
        "seq": event.seq,
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else _utc_now_iso(),
    }


def publish_agent_event(
    db: Session,
    execution_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    max_attempts = 5
    event: AgentExecutionEvent | None = None

    for _ in range(max_attempts):
        next_seq = (
            db.query(func.coalesce(func.max(AgentExecutionEvent.seq), 0))
            .filter(AgentExecutionEvent.execution_id == execution_id)
            .scalar()
            + 1
        )

        event = AgentExecutionEvent(
            execution_id=execution_id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
        )
        db.add(event)

        try:
            db.commit()
            db.refresh(event)
            break
        except IntegrityError:
            db.rollback()
            event = None
            continue

    if event is None:
        raise RuntimeError("Failed to assign deterministic sequence to agent execution event")

    message = _serialize_event(event)
    redis_connection.publish(get_agent_event_channel(str(execution_id)), json.dumps(message))
    return message


def build_transient_event(
    execution_id: str | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
    seq: int | None = None,
) -> dict[str, Any]:
    return {
        "id": None,
        "execution_id": execution_id,
        "seq": seq,
        "event_type": event_type,
        "payload": payload or {},
        "created_at": _utc_now_iso(),
    }


def get_agent_execution_events(db: Session, execution_id: UUID, limit: int = 500) -> list[dict[str, Any]]:
    rows = (
        db.query(AgentExecutionEvent)
        .filter(AgentExecutionEvent.execution_id == execution_id)
        .order_by(AgentExecutionEvent.seq.asc(), AgentExecutionEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    return [_serialize_event(row) for row in rows]

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.redis import redis_connection
from app.models.runtime_snapshot import RuntimeSnapshot


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_sandbox_event_channel(sandbox_id: str) -> str:
    return f"sandbox_events:{sandbox_id}"


def _serialize_event(event: RuntimeSnapshot) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "sandbox_id": str(event.sandbox_id),
        "seq": event.seq,
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else _utc_now_iso(),
    }


def publish_sandbox_event(
    db: Session,
    sandbox_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    max_attempts = 5
    event: RuntimeSnapshot | None = None

    for _ in range(max_attempts):
        next_seq = (
            db.query(func.coalesce(func.max(RuntimeSnapshot.seq), 0))
            .filter(RuntimeSnapshot.sandbox_id == sandbox_id)
            .scalar()
            + 1
        )

        event = RuntimeSnapshot(
            sandbox_id=sandbox_id,
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
        raise RuntimeError("Failed to assign deterministic sequence to sandbox event")

    message = _serialize_event(event)
    redis_connection.publish(get_sandbox_event_channel(str(sandbox_id)), json.dumps(message))
    return message


def get_runtime_snapshots(db: Session, sandbox_id: UUID, limit: int = 500) -> list[dict[str, Any]]:
    rows = (
        db.query(RuntimeSnapshot)
        .filter(RuntimeSnapshot.sandbox_id == sandbox_id)
        .order_by(RuntimeSnapshot.seq.asc(), RuntimeSnapshot.created_at.asc())
        .limit(limit)
        .all()
    )
    return [_serialize_event(row) for row in rows]

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.redis import get_async_redis_connection
from app.services.event_stream import get_execution_events, get_task_event_channel

router = APIRouter(tags=["events"])


@router.get("/tasks/{task_id}/events", status_code=status.HTTP_200_OK)
def get_task_events(task_id: UUID, db: Session = Depends(get_db)) -> dict:
    return {
        "task_id": str(task_id),
        "events": get_execution_events(db, task_id),
    }


@router.websocket("/ws/tasks/{task_id}")
async def task_events_ws(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()

    try:
        task_uuid = UUID(task_id)
    except ValueError:
        await websocket.send_json({"event_type": "error", "payload": {"message": "Invalid task_id"}})
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    redis_client = get_async_redis_connection()
    pubsub = redis_client.pubsub()
    channel = get_task_event_channel(task_id)

    try:
        replay_events = get_execution_events(db, task_uuid)
        await websocket.send_json({"event_type": "replay_start", "count": len(replay_events)})
        for event in replay_events:
            await websocket.send_json(event)
        await websocket.send_json({"event_type": "replay_complete", "count": len(replay_events)})

        await pubsub.subscribe(channel)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                raw_data = message.get("data")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")

                try:
                    parsed = json.loads(raw_data)
                except (TypeError, json.JSONDecodeError):
                    parsed = {"event_type": "raw", "payload": {"data": raw_data}}

                await websocket.send_json(parsed)

            await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        db.close()

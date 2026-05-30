import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.redis import get_agent_queue, get_async_redis_connection
from app.models.execution_artifact import ExecutionArtifact
from app.models.tool_invocation import ToolInvocation
from app.schemas.agent import (
    AgentCreate,
    AgentExecutionCreate,
    AgentExecutionRead,
    AgentMemoryCreate,
    AgentMemoryRead,
    AgentRead,
    AgentUpdate,
    ToolPermissionCreate,
    ToolPermissionRead,
)
from app.services import agent_service
from app.services.agent_event_stream import get_agent_event_channel, get_agent_execution_events

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db)) -> list[AgentRead]:
    agents = agent_service.list_agents(db)
    return [AgentRead.model_validate(agent) for agent in agents]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)) -> AgentRead:
    agent = agent_service.create_agent(db, payload.model_dump())
    return AgentRead.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: UUID, db: Session = Depends(get_db)) -> AgentRead:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return AgentRead.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(agent_id: UUID, payload: AgentUpdate, db: Session = Depends(get_db)) -> AgentRead:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    updated = agent_service.update_agent(db, agent, payload.model_dump(exclude_unset=True))
    return AgentRead.model_validate(updated)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: UUID, db: Session = Depends(get_db)) -> None:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent_service.delete_agent(db, agent)


@router.get("/{agent_id}/permissions", response_model=list[ToolPermissionRead])
def list_permissions(agent_id: UUID, db: Session = Depends(get_db)) -> list[ToolPermissionRead]:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    permissions = agent_service.list_permissions(db, agent_id)
    return [ToolPermissionRead.model_validate(permission) for permission in permissions]


@router.put("/{agent_id}/permissions", response_model=list[ToolPermissionRead])
def replace_permissions(
    agent_id: UUID,
    payload: list[ToolPermissionCreate],
    db: Session = Depends(get_db),
) -> list[ToolPermissionRead]:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    permissions = agent_service.replace_permissions(db, agent_id, [entry.model_dump() for entry in payload])
    return [ToolPermissionRead.model_validate(permission) for permission in permissions]


@router.get("/{agent_id}/executions", response_model=list[AgentExecutionRead])
def list_executions(agent_id: UUID, db: Session = Depends(get_db)) -> list[AgentExecutionRead]:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    executions = agent_service.list_executions(db, agent_id)
    return [AgentExecutionRead.model_validate(execution) for execution in executions]


@router.post("/{agent_id}/executions", response_model=AgentExecutionRead, status_code=status.HTTP_202_ACCEPTED)
def create_execution(
    agent_id: UUID,
    payload: AgentExecutionCreate,
    db: Session = Depends(get_db),
) -> AgentExecutionRead:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    execution = agent_service.create_execution(
        db,
        agent_id,
        payload.objective,
        payload.project_id,
        payload.session_id,
        payload.input,
    )

    queue = get_agent_queue()
    queue.enqueue("app.workers.agent_worker.process_agent_execution", str(execution.id), job_timeout=900)

    return AgentExecutionRead.model_validate(execution)


@router.get("/{agent_id}/memory", response_model=list[AgentMemoryRead])
def list_memory(
    agent_id: UUID,
    project_id: UUID | None = Query(default=None),
    scope: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AgentMemoryRead]:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    memories = agent_service.list_memory(db, agent_id, project_id=project_id, scope=scope)
    return [AgentMemoryRead.model_validate(memory) for memory in memories]


@router.post("/{agent_id}/memory", response_model=AgentMemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(
    agent_id: UUID,
    payload: AgentMemoryCreate,
    db: Session = Depends(get_db),
) -> AgentMemoryRead:
    agent = agent_service.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    memory = agent_service.create_memory(db, agent_id, payload.model_dump())
    return AgentMemoryRead.model_validate(memory)


@router.get("/executions/{execution_id}", response_model=AgentExecutionRead)
def get_execution(execution_id: UUID, db: Session = Depends(get_db)) -> AgentExecutionRead:
    execution = agent_service.get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return AgentExecutionRead.model_validate(execution)


@router.post("/executions/{execution_id}/cancel", response_model=AgentExecutionRead)
def cancel_execution(execution_id: UUID, db: Session = Depends(get_db)) -> AgentExecutionRead:
    execution = agent_service.get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    updated = agent_service.update_execution(db, execution, {"status": "canceled"})
    return AgentExecutionRead.model_validate(updated)


@router.get("/executions/{execution_id}/events", status_code=status.HTTP_200_OK)
def get_execution_events(execution_id: UUID, db: Session = Depends(get_db)) -> dict:
    return {
        "execution_id": str(execution_id),
        "events": get_agent_execution_events(db, execution_id),
    }


@router.get("/executions/{execution_id}/artifacts", status_code=status.HTTP_200_OK)
def get_execution_artifacts(execution_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(ExecutionArtifact)
        .filter(ExecutionArtifact.agent_execution_id == execution_id)
        .order_by(ExecutionArtifact.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(row.id),
            "artifact_type": row.artifact_type,
            "uri": row.uri,
            "metadata": row.metadata,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/executions/{execution_id}/tool-invocations", status_code=status.HTTP_200_OK)
def get_tool_invocations(execution_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(ToolInvocation)
        .filter(ToolInvocation.agent_execution_id == execution_id)
        .order_by(ToolInvocation.created_at.asc())
        .all()
    )
    return [
        {
            "id": str(row.id),
            "tool_name": row.tool_name,
            "status": row.status,
            "duration_ms": row.duration_ms,
            "input": row.input,
            "output": row.output,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.websocket("/ws/executions/{execution_id}")
async def execution_events_ws(websocket: WebSocket, execution_id: str) -> None:
    await websocket.accept()

    try:
        execution_uuid = UUID(execution_id)
    except ValueError:
        await websocket.send_json({"event_type": "error", "payload": {"message": "Invalid execution_id"}})
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    redis_client = get_async_redis_connection()
    pubsub = redis_client.pubsub()
    channel = get_agent_event_channel(execution_id)

    try:
        replay_events = get_agent_execution_events(db, execution_uuid)
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

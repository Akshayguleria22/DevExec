import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.redis import get_async_redis_connection
from app.models.artifact import Artifact
from app.schemas.sandbox import (
    ArtifactRead,
    ExecutionWorkspaceCreate,
    ExecutionWorkspaceRead,
    SandboxExecuteRequest,
    SandboxSessionCreate,
    SandboxSessionRead,
    ToolExecutionRead,
)
from app.services import sandbox_service, workspace_service
from app.services.sandbox_event_stream import get_runtime_snapshots, get_sandbox_event_channel

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


@router.post("/workspaces", response_model=ExecutionWorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: ExecutionWorkspaceCreate, db: Session = Depends(get_db)) -> ExecutionWorkspaceRead:
    workspace = workspace_service.create_workspace(db, payload.model_dump())
    return ExecutionWorkspaceRead.model_validate(workspace)


@router.get("/workspaces/{workspace_id}", response_model=ExecutionWorkspaceRead)
def get_workspace(workspace_id: UUID, db: Session = Depends(get_db)) -> ExecutionWorkspaceRead:
    workspace = workspace_service.get_workspace(db, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return ExecutionWorkspaceRead.model_validate(workspace)


@router.post("", response_model=SandboxSessionRead, status_code=status.HTTP_201_CREATED)
def create_sandbox_session(payload: SandboxSessionCreate, db: Session = Depends(get_db)) -> SandboxSessionRead:
    session = sandbox_service.create_sandbox_session(db, payload.model_dump())
    return SandboxSessionRead.model_validate(session)


@router.get("/{sandbox_id}", response_model=SandboxSessionRead)
def get_sandbox_session(sandbox_id: UUID, db: Session = Depends(get_db)) -> SandboxSessionRead:
    session = sandbox_service.get_sandbox_session(db, sandbox_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")
    return SandboxSessionRead.model_validate(session)


@router.post("/{sandbox_id}/execute", response_model=ToolExecutionRead, status_code=status.HTTP_201_CREATED)
def execute_tool(
    sandbox_id: UUID,
    payload: SandboxExecuteRequest,
    db: Session = Depends(get_db),
) -> ToolExecutionRead:
    session = sandbox_service.get_sandbox_session(db, sandbox_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")

    tool_exec = sandbox_service.create_tool_execution(db, session, payload.model_dump())
    return ToolExecutionRead.model_validate(tool_exec)


@router.post("/{sandbox_id}/stop", status_code=status.HTTP_200_OK)
def stop_sandbox_session(sandbox_id: UUID, db: Session = Depends(get_db)) -> dict:
    session = sandbox_service.get_sandbox_session(db, sandbox_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")
    sandbox_service.stop_sandbox_session(db, session)
    return {"status": "stopped"}


@router.get("/{sandbox_id}/events", status_code=status.HTTP_200_OK)
def get_sandbox_events(sandbox_id: UUID, db: Session = Depends(get_db)) -> dict:
    return {
        "sandbox_id": str(sandbox_id),
        "events": get_runtime_snapshots(db, sandbox_id),
    }


@router.get("/{sandbox_id}/tool-executions", response_model=list[ToolExecutionRead])
def list_tool_executions(sandbox_id: UUID, db: Session = Depends(get_db)) -> list[ToolExecutionRead]:
    rows = sandbox_service.list_tool_executions(db, sandbox_id)
    return [ToolExecutionRead.model_validate(row) for row in rows]


@router.get("/{sandbox_id}/artifacts", response_model=list[ArtifactRead])
def list_artifacts(sandbox_id: UUID, db: Session = Depends(get_db)) -> list[ArtifactRead]:
    rows = (
        db.query(Artifact)
        .filter(Artifact.sandbox_id == sandbox_id)
        .order_by(Artifact.created_at.desc())
        .all()
    )
    return [ArtifactRead.model_validate(row) for row in rows]


@router.websocket("/ws/sandboxes/{sandbox_id}")
async def sandbox_events_ws(websocket: WebSocket, sandbox_id: str) -> None:
    await websocket.accept()

    try:
        sandbox_uuid = UUID(sandbox_id)
    except ValueError:
        await websocket.send_json({"event_type": "error", "payload": {"message": "Invalid sandbox_id"}})
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    redis_client = get_async_redis_connection()
    pubsub = redis_client.pubsub()
    channel = get_sandbox_event_channel(sandbox_id)

    try:
        replay_events = get_runtime_snapshots(db, sandbox_uuid)
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

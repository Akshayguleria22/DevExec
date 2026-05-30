from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.session import ExecutionTaskCreate, ExecutionTaskRead, RuntimeSessionRead
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=RuntimeSessionRead)
def get_session(session_id: UUID, db: Session = Depends(get_db)) -> RuntimeSessionRead:
    session = session_service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return RuntimeSessionRead.model_validate(session)


@router.get("/{session_id}/tasks", response_model=list[ExecutionTaskRead])
def list_session_tasks(session_id: UUID, db: Session = Depends(get_db)) -> list[ExecutionTaskRead]:
    session = session_service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    tasks = session_service.list_execution_tasks(db, session_id)
    return [ExecutionTaskRead.model_validate(task) for task in tasks]


@router.post("/{session_id}/tasks", response_model=ExecutionTaskRead, status_code=status.HTTP_201_CREATED)
def create_session_task(
    session_id: UUID,
    payload: ExecutionTaskCreate,
    db: Session = Depends(get_db),
) -> ExecutionTaskRead:
    session = session_service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    task = session_service.create_execution_task(db, session, payload.instruction)
    return ExecutionTaskRead.model_validate(task)

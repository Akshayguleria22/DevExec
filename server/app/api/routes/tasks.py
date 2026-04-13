from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.task import TaskCreate, TaskCreateResponse, TaskRead
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> TaskCreateResponse:
    task = task_service.create_task(db, payload.input)
    task_service.enqueue_task(db, task)
    return TaskCreateResponse(task_id=task.id)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: UUID, db: Session = Depends(get_db)) -> TaskRead:
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskRead.model_validate(task)

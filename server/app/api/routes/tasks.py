from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.task import (
    ClosedLoopRequest,
    ClosedLoopResponse,
    TaskCreate,
    TaskCreateResponse,
    TaskRead,
)
from app.services import task_service
from app.services.closed_loop import execute_closed_loop
from app.services.metrics_collector import metrics_collector
from app.tools.registry import list_tools

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


@router.post("/closed-loop", response_model=ClosedLoopResponse, status_code=status.HTTP_200_OK)
def run_closed_loop(payload: ClosedLoopRequest) -> ClosedLoopResponse:
    """Execute a closed-loop diagnostic cycle: test → analyze → fix → re-test → compare."""
    result = execute_closed_loop(payload.model_dump())
    return ClosedLoopResponse(**result)


@router.get("/meta/tools", status_code=status.HTTP_200_OK)
def get_tools() -> list[dict]:
    """List all registered tools with metadata (for CI/CD and dashboard consumption)."""
    return list_tools()


@router.get("/meta/metrics", status_code=status.HTTP_200_OK)
def get_metrics() -> dict:
    """Return a metrics snapshot for monitoring and performance tracking."""
    return metrics_collector.get_snapshot()

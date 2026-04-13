from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
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
from app.services.metrics_collector import MetricsCollector, metrics_collector
from app.services.report_service import build_task_markdown_report, build_task_report, build_task_summary
from app.tools.registry import list_tools

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ---- Core task endpoints ----

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


@router.get("/{task_id}/summary", status_code=status.HTTP_200_OK)
def get_task_summary(task_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return build_task_summary(task)


@router.get("/{task_id}/report", status_code=status.HTTP_200_OK)
def get_task_report(
    task_id: UUID,
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    db: Session = Depends(get_db),
) -> Any:
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if format == "markdown":
        return PlainTextResponse(build_task_markdown_report(task), media_type="text/markdown")

    return build_task_report(task)


# ---- Closed-loop ----

@router.post("/closed-loop", response_model=ClosedLoopResponse, status_code=status.HTTP_200_OK)
def run_closed_loop(payload: ClosedLoopRequest, db: Session = Depends(get_db)) -> ClosedLoopResponse:
    """Execute a closed-loop diagnostic cycle with memory and regression detection."""
    result = execute_closed_loop(payload.model_dump(), db_session=db)
    return ClosedLoopResponse(**result)


# ---- Execution history ----

@router.get("/history/lookup", status_code=status.HTTP_200_OK)
def get_execution_history(
    fingerprint: str = Query(..., description="Task fingerprint to look up history for."),
    limit: int = Query(default=10, ge=1, le=50, description="Max number of history entries."),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve execution history for a given task fingerprint."""
    from app.services.execution_memory import get_history_by_fingerprint

    history = get_history_by_fingerprint(db, fingerprint, limit)
    return {
        "fingerprint": fingerprint,
        "count": len(history),
        "runs": history,
    }


# ---- Meta endpoints ----

@router.get("/meta/tools", status_code=status.HTTP_200_OK)
def get_tools() -> list[dict]:
    """List all registered tools with metadata."""
    return list_tools()


@router.get("/meta/metrics", status_code=status.HTTP_200_OK)
def get_metrics() -> dict:
    """Return in-memory metrics snapshot."""
    return metrics_collector.get_snapshot()


@router.get("/meta/metrics/db", status_code=status.HTTP_200_OK)
def get_db_metrics(
    tool_name: str | None = Query(default=None, description="Specific tool name, or omit for all."),
    db: Session = Depends(get_db),
) -> dict:
    """Return authoritative tool metrics from the database."""
    return MetricsCollector.get_tool_metrics_from_db(db, tool_name)

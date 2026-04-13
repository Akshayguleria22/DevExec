import json
import logging
from typing import Any
from uuid import UUID

from rq.job import Job
from sqlalchemy.orm import Session

from app.core.redis import get_task_queue
from app.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)


def normalize_input(raw_input: Any) -> str:
    if isinstance(raw_input, str):
        return raw_input
    return json.dumps(raw_input)


def create_task(db: Session, task_input: Any) -> Task:
    task = Task(
        input=normalize_input(task_input),
        status=TaskStatus.PENDING.value,
        warnings=[],
        step_errors=[],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("Created task %s.", task.id)
    return task


def enqueue_task(db: Session, task: Task) -> Job:
    queue = get_task_queue()
    try:
        job = queue.enqueue("app.workers.task_worker.process_task", str(task.id), job_timeout=600)
        task.status = TaskStatus.QUEUED.value
        db.commit()
        db.refresh(task)
        logger.info("Task %s enqueued as job %s.", task.id, job.id)
        return job
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.FAILED.value
        task.step_errors = [*(task.step_errors or []), {"step": "queue", "error": str(exc)}]
        db.commit()
        db.refresh(task)
        logger.error("Failed to enqueue task %s: %s", task.id, exc)
        raise


def get_task(db: Session, task_id: UUID) -> Task | None:
    return db.get(Task, task_id)


def mark_task_running(db: Session, task: Task) -> None:
    task.status = TaskStatus.RUNNING.value
    db.commit()
    db.refresh(task)
    logger.info("Task %s marked as running.", task.id)


def complete_task(
    db: Session,
    task: Task,
    result: dict[str, Any],
    warnings: list[Any],
    step_errors: list[dict[str, str]],
    execution_trace: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> None:
    """Complete a task and persist the full execution trace, metrics, and retry count."""
    task.result = result
    task.warnings = warnings
    task.step_errors = step_errors
    task.execution_trace = execution_trace
    task.metrics = metrics
    task.retry_count = retry_count
    task.status = TaskStatus.COMPLETED.value if not step_errors else TaskStatus.FAILED.value
    db.commit()
    db.refresh(task)
    logger.info("Task %s completed with status '%s'. Retries: %d.", task.id, task.status, retry_count)


def fail_task(db: Session, task: Task, error: str) -> None:
    task.status = TaskStatus.FAILED.value
    task.step_errors = [*(task.step_errors or []), {"step": "worker", "error": error}]
    db.commit()
    db.refresh(task)
    logger.error("Task %s failed: %s", task.id, error)

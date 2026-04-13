import json
from typing import Any
from uuid import UUID

from rq.job import Job
from sqlalchemy.orm import Session

from app.core.redis import get_task_queue
from app.models.task import Task, TaskStatus


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
    return task


def enqueue_task(db: Session, task: Task) -> Job:
    queue = get_task_queue()
    try:
        job = queue.enqueue("app.workers.task_worker.process_task", str(task.id), job_timeout=600)
        task.status = TaskStatus.QUEUED.value
        db.commit()
        db.refresh(task)
        return job
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.FAILED.value
        task.step_errors = [*(task.step_errors or []), {"step": "queue", "error": str(exc)}]
        db.commit()
        db.refresh(task)
        raise


def get_task(db: Session, task_id: UUID) -> Task | None:
    return db.get(Task, task_id)


def mark_task_running(db: Session, task: Task) -> None:
    task.status = TaskStatus.RUNNING.value
    db.commit()
    db.refresh(task)


def complete_task(
    db: Session,
    task: Task,
    result: dict[str, Any],
    warnings: list[Any],
    step_errors: list[dict[str, str]],
) -> None:
    task.result = result
    task.warnings = warnings
    task.step_errors = step_errors
    task.status = TaskStatus.COMPLETED.value if not step_errors else TaskStatus.FAILED.value
    db.commit()
    db.refresh(task)


def fail_task(db: Session, task: Task, error: str) -> None:
    task.status = TaskStatus.FAILED.value
    task.step_errors = [*(task.step_errors or []), {"step": "worker", "error": error}]
    db.commit()
    db.refresh(task)

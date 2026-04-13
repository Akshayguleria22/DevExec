"""Task Worker — processes queued tasks via the execution engine and persists results."""

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.services.execution_engine import run_execution
from app.services.metrics_collector import metrics_collector
from app.services.task_service import complete_task, fail_task, get_task, mark_task_running

logger = logging.getLogger(__name__)


def process_task(task_id: str) -> None:
    db = SessionLocal()
    task = None

    try:
        task_uuid = UUID(task_id)
        task = get_task(db, task_uuid)
        if task is None:
            logger.warning("Task %s not found in database. Skipping.", task_id)
            return

        mark_task_running(db, task)
        logger.info("Processing task %s.", task_id)

        execution_output = run_execution(task.input)

        # Extract metrics for tracking
        steps = execution_output.get("steps", [])
        total_retries = execution_output.get("total_retries", 0)
        total_duration = execution_output.get("duration_ms", 0)

        # Build execution trace for persistence
        execution_trace = {
            "steps": [
                {
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "duration_ms": s.get("duration_ms"),
                    "attempts": s.get("attempts"),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                }
                for s in steps
            ],
            "start_time": execution_output.get("start_time"),
            "end_time": execution_output.get("end_time"),
            "duration_ms": total_duration,
        }

        # Build metrics summary
        task_metrics = {
            "total_steps": len(steps),
            "completed_steps": sum(1 for s in steps if s.get("status") == "completed"),
            "failed_steps": sum(1 for s in steps if s.get("status") == "failed"),
            "total_retries": total_retries,
            "total_duration_ms": total_duration,
        }

        # Record in metrics collector
        for s in steps:
            metrics_collector.record_tool_execution(
                tool_name=s.get("name", "unknown"),
                duration_ms=s.get("duration_ms", 0),
                success=s.get("status") == "completed",
                attempts=s.get("attempts", 1),
            )

        metrics_collector.record_execution_summary(
            task_id=task_id,
            total_duration_ms=total_duration,
            steps_completed=task_metrics["completed_steps"],
            steps_failed=task_metrics["failed_steps"],
            total_retries=total_retries,
        )

        complete_task(
            db=db,
            task=task,
            result=execution_output,
            warnings=execution_output.get("warnings", []),
            step_errors=execution_output.get("step_errors", []),
            execution_trace=execution_trace,
            metrics=task_metrics,
            retry_count=total_retries,
        )

        logger.info("Task %s completed successfully.", task_id)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Task %s failed with exception.", task_id)
        if task is not None:
            fail_task(db, task, str(exc))
        raise
    finally:
        db.close()

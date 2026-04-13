"""Task Worker — processes queued tasks with full memory, regression, and metrics integration."""

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.services.execution_engine import run_execution
from app.services.metrics_collector import metrics_collector
from app.services.notification_service import send_task_notifications
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

        # Pass DB session so the engine can use execution memory + regression detection
        enhanced_output = run_execution(task.input, db_session=db, task_id=task.id)

        # The engine now returns enhanced output: {execution, comparison, regression, tool_metrics}
        execution_data = enhanced_output.get("execution", {})
        regression_data = enhanced_output.get("regression")
        comparison_data = enhanced_output.get("comparison")
        tool_metrics_data = enhanced_output.get("tool_metrics")

        # Extract step-level data from the execution block
        steps = execution_data.get("steps", [])
        total_retries = execution_data.get("total_retries", 0)
        total_duration = execution_data.get("duration_ms", 0)

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
            "start_time": execution_data.get("start_time"),
            "end_time": execution_data.get("end_time"),
            "duration_ms": total_duration,
        }

        # Build comprehensive metrics for persistence
        task_metrics = {
            "total_steps": len(steps),
            "completed_steps": sum(1 for s in steps if s.get("status") == "completed"),
            "failed_steps": sum(1 for s in steps if s.get("status") == "failed"),
            "total_retries": total_retries,
            "total_duration_ms": total_duration,
            "events_emitted": len(enhanced_output.get("events", [])),
            "regression": regression_data,
            "comparison": comparison_data,
            "tool_metrics_snapshot": tool_metrics_data,
        }

        # Record execution summary in collector
        metrics_collector.record_execution_summary(
            task_id=task_id,
            total_duration_ms=total_duration,
            steps_completed=task_metrics["completed_steps"],
            steps_failed=task_metrics["failed_steps"],
            total_retries=total_retries,
        )

        # Persist task with full enhanced output
        complete_task(
            db=db,
            task=task,
            result=enhanced_output,
            warnings=execution_data.get("warnings", []),
            step_errors=execution_data.get("step_errors", []),
            execution_trace=execution_trace,
            metrics=task_metrics,
            retry_count=total_retries,
        )

        persisted_task = get_task(db, task_uuid)
        if persisted_task is not None:
            send_task_notifications(persisted_task)

        logger.info("Task %s completed successfully.", task_id)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Task %s failed with exception.", task_id)
        if task is not None:
            fail_task(db, task, str(exc))
            failed_task = get_task(db, task_uuid)
            if failed_task is not None:
                send_task_notifications(failed_task)
        raise
    finally:
        db.close()

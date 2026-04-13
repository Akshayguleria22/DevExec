from uuid import UUID

from app.core.database import SessionLocal
from app.services.execution_engine import run_execution
from app.services.task_service import complete_task, fail_task, get_task, mark_task_running


def process_task(task_id: str) -> None:
    db = SessionLocal()
    task = None

    try:
        task_uuid = UUID(task_id)
        task = get_task(db, task_uuid)
        if task is None:
            return

        mark_task_running(db, task)
        execution_output = run_execution(task.input)

        complete_task(
            db=db,
            task=task,
            result=execution_output,
            warnings=execution_output.get("warnings", []),
            step_errors=execution_output.get("step_errors", []),
        )
    except Exception as exc:  # noqa: BLE001
        if task is not None:
            fail_task(db, task, str(exc))
        raise
    finally:
        db.close()

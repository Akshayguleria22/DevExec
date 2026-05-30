from sqlalchemy.orm import Session

from app.models.execution_task import ExecutionTask
from app.models.runtime_session import RuntimeSession
from app.models.task import TaskStatus
from app.services import task_service


def create_session(db: Session, project_id, title: str, summary: str = "") -> RuntimeSession:
    session = RuntimeSession(
        project_id=project_id,
        title=title,
        summary=summary,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, project_id=None) -> list[RuntimeSession]:
    query = db.query(RuntimeSession)
    if project_id is not None:
        query = query.filter(RuntimeSession.project_id == project_id)
    return query.order_by(RuntimeSession.updated_at.desc()).all()


def get_session(db: Session, session_id) -> RuntimeSession | None:
    return db.get(RuntimeSession, session_id)


def _summarize_instruction(instruction: str, max_len: int = 140) -> str:
    trimmed = instruction.strip()
    if len(trimmed) <= max_len:
        return trimmed
    return trimmed[: max_len - 3].rstrip() + "..."


def create_execution_task(db: Session, session: RuntimeSession, instruction: str) -> ExecutionTask:
    payload = {
        "instruction": instruction,
        "project_context_id": str(session.project_id),
        "runtime_session_id": str(session.id),
    }
    task = task_service.create_task(db, payload)
    task_service.enqueue_task(db, task)

    execution_task = ExecutionTask(
        session_id=session.id,
        task_id=task.id,
        title="Runtime execution",
        summary=_summarize_instruction(instruction),
        status=TaskStatus.QUEUED.value,
    )
    db.add(execution_task)
    db.commit()
    db.refresh(execution_task)
    return execution_task


def list_execution_tasks(db: Session, session_id) -> list[ExecutionTask]:
    return (
        db.query(ExecutionTask)
        .filter(ExecutionTask.session_id == session_id)
        .order_by(ExecutionTask.updated_at.desc())
        .all()
    )

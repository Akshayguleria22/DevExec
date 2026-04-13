"""Execution Memory — persistent storage and retrieval of execution history.

Stores the last N runs per task fingerprint. Provides:
  - record_run(): persist a new execution snapshot
  - get_history(): retrieve recent runs for a task type
  - get_latest_run(): get the most recent run for comparison
  - compute_fingerprint(): deterministic task input hashing

Separated from execution engine for clean architecture (Part 7).
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.execution_history import ExecutionHistory

logger = logging.getLogger(__name__)

# Maximum number of historical runs to keep per task fingerprint
MAX_HISTORY_PER_FINGERPRINT = 20


def compute_fingerprint(task_input: str) -> str:
    """Create a deterministic fingerprint from task input.

    Normalizes the input (sorts JSON keys, strips whitespace) before hashing
    so that semantically equivalent inputs produce the same fingerprint.
    """
    try:
        parsed = json.loads(task_input)
        normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        normalized = task_input.strip()

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def record_run(
    db: Session,
    task_id: str | None,
    task_input: str,
    metrics: dict[str, Any],
    execution_trace: dict[str, Any] | None = None,
) -> ExecutionHistory:
    """Persist an execution run to the history table.

    Args:
        db: Database session.
        task_id: UUID string of the originating task (can be None for closed-loop).
        task_input: Raw task input string.
        metrics: Dict with keys: success_rate, latency_ms, total_tests, passed_tests,
                 failed_tests, total_retries, duration_ms.
        execution_trace: Optional full trace snapshot.

    Returns:
        The created ExecutionHistory record.
    """
    fingerprint = compute_fingerprint(task_input)

    import uuid as _uuid

    record = ExecutionHistory(
        task_id=_uuid.UUID(task_id) if task_id else None,
        task_fingerprint=fingerprint,
        task_input=task_input,
        success_rate=metrics.get("success_rate", 0.0),
        latency_ms=metrics.get("latency_ms", 0.0),
        total_tests=metrics.get("total_tests", 0),
        passed_tests=metrics.get("passed_tests", 0),
        failed_tests=metrics.get("failed_tests", 0),
        total_retries=metrics.get("total_retries", 0),
        duration_ms=metrics.get("duration_ms", 0),
        execution_trace=execution_trace,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Prune old entries beyond MAX_HISTORY
    _prune_old_entries(db, fingerprint)

    logger.info(
        "Recorded execution history: fingerprint=%s, success_rate=%.1f%%, latency=%.1fms.",
        fingerprint,
        record.success_rate,
        record.latency_ms,
    )
    return record


def get_history(
    db: Session,
    task_input: str,
    limit: int = MAX_HISTORY_PER_FINGERPRINT,
) -> list[dict[str, Any]]:
    """Retrieve the most recent N runs for a given task input fingerprint.

    Returns list of dicts ordered newest-first.
    """
    fingerprint = compute_fingerprint(task_input)
    return get_history_by_fingerprint(db, fingerprint, limit)


def get_history_by_fingerprint(
    db: Session,
    fingerprint: str,
    limit: int = MAX_HISTORY_PER_FINGERPRINT,
) -> list[dict[str, Any]]:
    """Retrieve history by fingerprint directly."""
    records = (
        db.query(ExecutionHistory)
        .filter(ExecutionHistory.task_fingerprint == fingerprint)
        .order_by(desc(ExecutionHistory.created_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "task_id": str(r.task_id) if r.task_id else None,
            "task_input": r.task_input,
            "timestamp": r.created_at.isoformat(),
            "metrics": {
                "success_rate": r.success_rate,
                "latency_ms": r.latency_ms,
                "total_tests": r.total_tests,
                "passed_tests": r.passed_tests,
                "failed_tests": r.failed_tests,
                "total_retries": r.total_retries,
                "duration_ms": r.duration_ms,
            },
        }
        for r in records
    ]


def get_latest_run(db: Session, task_input: str) -> dict[str, Any] | None:
    """Get the single most recent run for a task input fingerprint."""
    history = get_history(db, task_input, limit=1)
    return history[0] if history else None


def get_previous_run(db: Session, task_input: str) -> dict[str, Any] | None:
    """Get the second most recent run (the one before the current).

    Used for regression comparison after recording the current run.
    """
    history = get_history(db, task_input, limit=2)
    return history[1] if len(history) >= 2 else None


def _prune_old_entries(db: Session, fingerprint: str) -> None:
    """Remove entries beyond MAX_HISTORY_PER_FINGERPRINT for a given fingerprint."""
    count = (
        db.query(ExecutionHistory)
        .filter(ExecutionHistory.task_fingerprint == fingerprint)
        .count()
    )
    if count <= MAX_HISTORY_PER_FINGERPRINT:
        return

    # Get IDs of excess (oldest) entries
    excess = (
        db.query(ExecutionHistory.id)
        .filter(ExecutionHistory.task_fingerprint == fingerprint)
        .order_by(desc(ExecutionHistory.created_at))
        .offset(MAX_HISTORY_PER_FINGERPRINT)
        .all()
    )
    excess_ids = [row[0] for row in excess]
    if excess_ids:
        db.query(ExecutionHistory).filter(ExecutionHistory.id.in_(excess_ids)).delete(synchronize_session=False)
        db.commit()
        logger.debug("Pruned %d old entries for fingerprint %s.", len(excess_ids), fingerprint)

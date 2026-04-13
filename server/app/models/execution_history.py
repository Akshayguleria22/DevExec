"""Execution History model — persistent storage for execution runs per task type.

Stores the last N runs per task input fingerprint so the system can:
  - compare current vs previous runs
  - detect regressions over time
  - build historical baselines
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExecutionHistory(Base):
    __tablename__ = "execution_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Links back to the task that produced this run
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Fingerprint of the task input — used to group runs of the same "type"
    # (e.g. same URL + method combo). Computed as a hash or normalized key.
    task_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # The raw task input that produced this run
    task_input: Mapped[str] = mapped_column(Text, nullable=False)

    # Snapshot metrics for this run
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Full execution trace snapshot (optional, for deep debugging)
    execution_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""Tool Metrics model — persistent per-tool performance aggregates.

Stores rolling aggregates per tool so the system can:
  - track performance over time
  - detect tool-level regressions
  - expose dashboards via API
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ToolMetrics(Base):
    __tablename__ = "tool_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Latency aggregates (tracked incrementally)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Computed on read: avg_latency = total_latency / total_calls
    # Not stored to avoid drift from batched updates.

    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return round(self.total_latency_ms / self.total_calls, 2)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return round(self.success_count / self.total_calls * 100, 2)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "avg_latency_ms": self.avg_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "success_rate": self.success_rate,
            "last_executed_at": self.last_executed_at.isoformat() if self.last_executed_at else None,
        }

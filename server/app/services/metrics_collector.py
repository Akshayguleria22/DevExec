"""Metrics Collector — hybrid in-memory + DB-persistent tool metrics system.

Provides:
  - record_tool_execution(): track individual tool calls (in-memory + flush to DB)
  - record_execution_summary(): track overall execution runs
  - get_tool_metrics(): aggregate per-tool stats
  - get_snapshot(): full metrics snapshot for API/dashboard consumption
  - flush_to_db(): persist in-memory counters to the tool_metrics DB table

Architecture:
  - In-memory counters for hot-path performance (no DB round-trip per call)
  - Periodic or on-demand flush to PostgreSQL for durability
  - DB read for authoritative stats via get_tool_metrics_from_db()
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.tool_metrics import ToolMetrics

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Hybrid metrics collector: fast in-memory writes, durable DB persistence."""

    def __init__(self) -> None:
        # In-memory hot counters (flushed to DB periodically)
        self._tool_calls: dict[str, int] = defaultdict(int)
        self._tool_successes: dict[str, int] = defaultdict(int)
        self._tool_failures: dict[str, int] = defaultdict(int)
        self._tool_latencies: dict[str, list[float]] = defaultdict(list)
        self._execution_summaries: list[dict[str, Any]] = []

    # ---- Recording (hot path — in-memory only) ----

    def record_tool_execution(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool,
        attempts: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a single tool execution in memory."""
        self._tool_calls[tool_name] += 1
        self._tool_latencies[tool_name].append(float(duration_ms))

        if success:
            self._tool_successes[tool_name] += 1
        else:
            self._tool_failures[tool_name] += 1

        logger.debug(
            "Tool metric recorded: %s, %dms, success=%s, attempt=%d",
            tool_name, duration_ms, success, attempts,
        )

    def record_execution_summary(
        self,
        task_id: str,
        total_duration_ms: int,
        steps_completed: int,
        steps_failed: int,
        total_retries: int,
    ) -> None:
        """Record an overall execution summary in memory."""
        summary = {
            "task_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_duration_ms": total_duration_ms,
            "steps_completed": steps_completed,
            "steps_failed": steps_failed,
            "total_retries": total_retries,
        }
        self._execution_summaries.append(summary)

        # Cap in-memory summaries to last 100
        if len(self._execution_summaries) > 100:
            self._execution_summaries = self._execution_summaries[-100:]

    # ---- Querying (in-memory fast read) ----

    def get_tool_metrics(self, tool_name: str | None = None) -> dict[str, Any]:
        """Get in-memory aggregate stats for one or all tools.

        This is the function exposed per Part 3 requirements.
        """
        if tool_name:
            return self._compute_tool_stats(tool_name)

        return {
            name: self._compute_tool_stats(name)
            for name in sorted(self._tool_calls.keys())
        }

    def _compute_tool_stats(self, tool_name: str) -> dict[str, Any]:
        total = self._tool_calls.get(tool_name, 0)
        successes = self._tool_successes.get(tool_name, 0)
        failures = self._tool_failures.get(tool_name, 0)
        latencies = self._tool_latencies.get(tool_name, [])

        if total == 0:
            return {
                "tool_name": tool_name,
                "total_calls": 0,
                "success_count": 0,
                "failure_count": 0,
                "avg_latency_ms": 0.0,
                "min_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "success_rate": 0.0,
            }

        return {
            "tool_name": tool_name,
            "total_calls": total,
            "success_count": successes,
            "failure_count": failures,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "min_latency_ms": round(min(latencies), 2) if latencies else 0.0,
            "max_latency_ms": round(max(latencies), 2) if latencies else 0.0,
            "success_rate": round(successes / total * 100, 2),
        }

    def get_snapshot(self) -> dict[str, Any]:
        """Return a full metrics snapshot for API/dashboard consumption."""
        return {
            "tool_metrics": self.get_tool_metrics(),
            "total_executions": len(self._execution_summaries),
            "recent_executions": self._execution_summaries[-10:],
        }

    # ---- DB Persistence ----

    def flush_to_db(self, db: Session) -> None:
        """Flush in-memory counters to the tool_metrics DB table.

        Uses upsert logic: creates rows for new tools, increments for existing.
        """
        now = datetime.now(timezone.utc)

        for tool_name in self._tool_calls:
            calls = self._tool_calls[tool_name]
            successes = self._tool_successes[tool_name]
            failures = self._tool_failures[tool_name]
            latencies = self._tool_latencies.get(tool_name, [])

            if calls == 0:
                continue

            total_latency = sum(latencies)
            min_lat = min(latencies) if latencies else 0.0
            max_lat = max(latencies) if latencies else 0.0

            existing = db.query(ToolMetrics).filter(ToolMetrics.tool_name == tool_name).first()

            if existing:
                existing.total_calls += calls
                existing.success_count += successes
                existing.failure_count += failures
                existing.total_latency_ms += total_latency
                existing.min_latency_ms = min(existing.min_latency_ms, min_lat) if existing.total_calls > calls else min_lat
                existing.max_latency_ms = max(existing.max_latency_ms, max_lat)
                existing.last_executed_at = now
            else:
                new_record = ToolMetrics(
                    tool_name=tool_name,
                    total_calls=calls,
                    success_count=successes,
                    failure_count=failures,
                    total_latency_ms=total_latency,
                    min_latency_ms=min_lat,
                    max_latency_ms=max_lat,
                    last_executed_at=now,
                )
                db.add(new_record)

        db.commit()

        # Reset in-memory counters after flush
        self._tool_calls.clear()
        self._tool_successes.clear()
        self._tool_failures.clear()
        self._tool_latencies.clear()

        logger.info("Flushed tool metrics to database.")

    @staticmethod
    def get_tool_metrics_from_db(db: Session, tool_name: str | None = None) -> dict[str, Any]:
        """Read authoritative tool metrics from the database."""
        if tool_name:
            record = db.query(ToolMetrics).filter(ToolMetrics.tool_name == tool_name).first()
            if record:
                return record.to_dict()
            return {"tool_name": tool_name, "total_calls": 0, "note": "No data yet."}

        records = db.query(ToolMetrics).all()
        return {r.tool_name: r.to_dict() for r in records}


# Module-level singleton
metrics_collector = MetricsCollector()

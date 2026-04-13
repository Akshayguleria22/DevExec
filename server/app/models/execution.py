"""Execution result model — typed representation of a full execution output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    """Result of a single tool execution step."""

    name: str
    status: str  # "completed" | "failed"
    start_time: str
    end_time: str
    duration_ms: int
    attempts: int
    output: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class ExecutionResult:
    """Full execution output with steps, timing, warnings, and errors."""

    steps: list[StepResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    step_errors: list[dict[str, str]] = field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int = 0
    total_retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "warnings": self.warnings,
            "step_errors": self.step_errors,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "total_retries": self.total_retries,
        }

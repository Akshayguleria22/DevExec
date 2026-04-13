from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    input: Any = Field(..., description="Natural language text or structured task input.")


class TaskCreateResponse(BaseModel):
    task_id: UUID


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    result: dict[str, Any] | None
    warnings: list[Any]
    step_errors: list[Any]
    execution_trace: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime


class ClosedLoopRequest(BaseModel):
    """Request body for the closed-loop execution endpoint."""

    url: str = Field(..., description="Target API URL to test.")
    method: str = Field(default="GET", description="HTTP method.")
    headers: dict[str, str] = Field(default_factory=dict, description="Request headers.")
    body: Any = Field(default=None, description="Request body.")
    logs: str | None = Field(default=None, description="Optional log text to analyze if provided.")


class ClosedLoopResponse(BaseModel):
    """Response from the closed-loop execution with memory and regression."""

    before: dict[str, Any]
    after: dict[str, Any]
    improvement: dict[str, Any]
    analysis: dict[str, Any]
    regression: dict[str, Any] | None = None
    tool_metrics: dict[str, Any] | None = None
    execution_trace: dict[str, Any]


class ExecutionHistoryResponse(BaseModel):
    """Response for history lookup endpoint."""

    fingerprint: str
    count: int
    runs: list[dict[str, Any]]


class ToolMetricsResponse(BaseModel):
    """Response for DB-persisted tool metrics."""

    tool_name: str
    total_calls: int
    success_count: int
    failure_count: int
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    success_rate: float
    last_executed_at: str | None = None

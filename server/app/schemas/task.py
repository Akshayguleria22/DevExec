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
    """Response from the closed-loop execution."""

    before: dict[str, Any]
    after: dict[str, Any]
    improvement: dict[str, Any]
    analysis: dict[str, Any]
    execution_trace: dict[str, Any]

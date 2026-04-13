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
    created_at: datetime
    updated_at: datetime

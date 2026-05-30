from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RuntimeSessionCreate(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(default="")


class RuntimeSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    summary: str
    status: str
    created_at: datetime
    updated_at: datetime


class ExecutionTaskCreate(BaseModel):
    instruction: str = Field(..., min_length=1)


class ExecutionTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    task_id: UUID | None
    title: str
    summary: str
    status: str
    created_at: datetime
    updated_at: datetime

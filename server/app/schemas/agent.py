from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field(default="")
    agent_type: str = Field(default="diagnostic")
    instructions: str = Field(default="")
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    runtime_settings: dict[str, Any] = Field(default_factory=dict)
    memory_config: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="active")


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    agent_type: str | None = None
    instructions: str | None = None
    execution_policy: dict[str, Any] | None = None
    runtime_settings: dict[str, Any] | None = None
    memory_config: dict[str, Any] | None = None
    status: str | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    agent_type: str
    instructions: str
    execution_policy: dict[str, Any]
    runtime_settings: dict[str, Any]
    memory_config: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class ToolPermissionCreate(BaseModel):
    tool_name: str = Field(..., min_length=1)
    allowed: bool = Field(default=True)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    tool_name: str
    allowed: bool
    config: dict[str, Any]
    created_at: datetime


class AgentExecutionCreate(BaseModel):
    objective: str = Field(..., min_length=4)
    project_id: UUID | None = None
    session_id: UUID | None = None
    input: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    project_id: UUID | None
    session_id: UUID | None
    parent_execution_id: UUID | None
    objective: str
    status: str
    plan: dict[str, Any]
    input: dict[str, Any]
    output: dict[str, Any]
    runtime_state: dict[str, Any]
    metrics: dict[str, Any]
    error: str
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentMemoryCreate(BaseModel):
    project_id: UUID | None = None
    execution_id: UUID | None = None
    scope: str = Field(default="runtime")
    key: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="")


class AgentMemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    project_id: UUID | None
    execution_id: UUID | None
    scope: str
    key: str
    payload: dict[str, Any]
    summary: str
    created_at: datetime
    updated_at: datetime

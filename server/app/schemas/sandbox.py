from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionWorkspaceCreate(BaseModel):
    project_id: UUID | None = None
    source_type: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionWorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    source_type: str
    source_ref: str
    mount_path: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SandboxSessionCreate(BaseModel):
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    agent_execution_id: UUID | None = None
    policy: dict[str, Any] = Field(default_factory=dict)
    runtime_settings: dict[str, Any] = Field(default_factory=dict)
    network_enabled: bool | None = None
    expires_in_seconds: int | None = None


class SandboxSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    project_id: UUID | None
    agent_execution_id: UUID | None
    status: str
    image: str
    container_id: str
    policy: dict[str, Any]
    runtime_settings: dict[str, Any]
    network_enabled: bool
    workspace_mount: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SandboxExecuteRequest(BaseModel):
    tool_name: str = Field(..., min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    command: str | None = None


class RuntimeSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sandbox_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class ToolExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sandbox_id: UUID
    tool_name: str
    status: str
    command: str
    input: dict[str, Any]
    output: dict[str, Any]
    stdout: str
    stderr: str
    duration_ms: float
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sandbox_id: UUID | None
    workspace_id: UUID | None
    tool_execution_id: UUID | None
    artifact_type: str
    uri: str
    metadata: dict[str, Any]
    created_at: datetime

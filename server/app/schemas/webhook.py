from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DeployWebhookRequest(BaseModel):
    repo_name: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    api_base_url: str = Field(..., min_length=1)
    commit_sha: str | None = None
    expand_endpoints: bool = Field(default=False)


class DeployWebhookResponse(BaseModel):
    deployment_event_id: UUID | None = None
    task_id: UUID | None = None
    generated_task: str | None = None
    duplicate_delivery: bool = False
    reused_task: bool = False
    message: str | None = None
    endpoints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    task_input: dict[str, Any] = Field(default_factory=dict)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1)
    input_type: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    input_type: str
    source_ref: str
    status: str
    detected_stack: dict
    metadata: dict
    created_at: datetime
    updated_at: datetime

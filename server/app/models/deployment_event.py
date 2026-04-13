import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    commit_sha: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    api_base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    generated_task_input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    discovered_endpoints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

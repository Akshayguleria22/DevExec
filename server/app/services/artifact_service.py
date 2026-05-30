import os
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.artifact import Artifact


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def persist_artifact(
    db: Session,
    artifact_type: str,
    content: bytes,
    filename: str,
    sandbox_id: UUID | None = None,
    workspace_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    base_root = settings.sandbox_artifact_root.rstrip("/\\")
    sandbox_folder = str(sandbox_id) if sandbox_id else "shared"
    artifact_dir = os.path.join(base_root, sandbox_folder)
    _ensure_dir(artifact_dir)

    file_path = os.path.join(artifact_dir, filename)
    with open(file_path, "wb") as handle:
        handle.write(content)

    uri = f"local://artifacts/{sandbox_folder}/{filename}"

    artifact = Artifact(
        sandbox_id=sandbox_id,
        workspace_id=workspace_id,
        tool_execution_id=tool_execution_id,
        artifact_type=artifact_type,
        uri=uri,
        metadata=metadata or {},
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact

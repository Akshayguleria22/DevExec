import json
import logging
import os
import shutil
import subprocess
import zipfile
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.execution_workspace import ExecutionWorkspace

logger = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_clone_repo(repo_url: str, target_path: str) -> None:
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, target_path],
        check=True,
        capture_output=True,
    )


def _extract_zip(zip_path: str, target_path: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target_path)


def _copy_local(src_path: str, target_path: str) -> None:
    shutil.copytree(src_path, target_path, dirs_exist_ok=True)


def _write_openapi(source_ref: str, target_path: str) -> None:
    _ensure_dir(target_path)
    openapi_path = os.path.join(target_path, "openapi.json")
    try:
        payload = json.loads(source_ref)
        with open(openapi_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except json.JSONDecodeError:
        with open(openapi_path, "w", encoding="utf-8") as handle:
            handle.write(source_ref)


def create_workspace(db: Session, payload: dict[str, Any]) -> ExecutionWorkspace:
    workspace = ExecutionWorkspace(
        project_id=payload.get("project_id"),
        source_type=payload.get("source_type"),
        source_ref=payload.get("source_ref"),
        metadata=payload.get("metadata", {}),
        status="provisioning",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    workspace_root = settings.sandbox_workspace_root.rstrip("/\\")
    target_path = os.path.join(workspace_root, str(workspace.id))
    _ensure_dir(target_path)

    try:
        source_type = workspace.source_type.lower()
        if source_type == "github":
            _safe_clone_repo(workspace.source_ref, target_path)
        elif source_type == "zip":
            _extract_zip(workspace.source_ref, target_path)
        elif source_type == "openapi":
            _write_openapi(workspace.source_ref, target_path)
        elif source_type == "local":
            _copy_local(workspace.source_ref, target_path)
        else:
            raise ValueError(f"Unsupported source_type: {workspace.source_type}")

        workspace.mount_path = target_path
        workspace.status = "ready"
        db.commit()
        db.refresh(workspace)
    except Exception as exc:  # noqa: BLE001
        workspace.status = "failed"
        db.commit()
        logger.exception("Failed to provision workspace %s: %s", workspace.id, exc)
        raise

    return workspace


def get_workspace(db: Session, workspace_id: UUID) -> ExecutionWorkspace | None:
    return db.get(ExecutionWorkspace, workspace_id)

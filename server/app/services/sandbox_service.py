from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.sandbox_session import SandboxSession
from app.models.tool_execution import ToolExecution
from app.services import artifact_service
from app.services.sandbox_event_stream import publish_sandbox_event
from app.services.sandbox_runtime import SandboxRuntimeError, execute_tool, start_container, stop_container
from app.services.workspace_service import create_workspace, get_workspace

logger = logging.getLogger(__name__)


def create_sandbox_session(db: Session, payload: dict[str, Any]) -> SandboxSession:
    workspace = None
    if payload.get("workspace_id"):
        workspace = get_workspace(db, payload["workspace_id"])

    if payload.get("workspace"):
        workspace = create_workspace(db, payload["workspace"])

    network_enabled = payload.get("network_enabled")
    if network_enabled is None:
        network_enabled = settings.sandbox_network_enabled

    expires_at = None
    if payload.get("expires_in_seconds"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload["expires_in_seconds"]))

    session = SandboxSession(
        workspace_id=workspace.id if workspace else None,
        project_id=payload.get("project_id"),
        agent_execution_id=payload.get("agent_execution_id"),
        status="provisioning",
        image=settings.sandbox_image,
        policy=payload.get("policy", {}),
        runtime_settings=payload.get("runtime_settings", {}),
        network_enabled=network_enabled,
        workspace_mount=workspace.mount_path if workspace else "",
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        container_id = start_container(session.workspace_mount or None, network_enabled)
        session.container_id = container_id
        session.status = "ready"
        db.commit()
        db.refresh(session)
        publish_sandbox_event(db, session.id, "sandbox_ready", {"container_id": container_id})
    except SandboxRuntimeError as exc:
        session.status = "failed"
        db.commit()
        publish_sandbox_event(db, session.id, "sandbox_failed", {"error": str(exc)})
        raise

    return session


def get_sandbox_session(db: Session, sandbox_id: UUID) -> SandboxSession | None:
    return db.get(SandboxSession, sandbox_id)


def stop_sandbox_session(db: Session, session: SandboxSession) -> None:
    stop_container(session.container_id)
    session.status = "stopped"
    db.commit()
    publish_sandbox_event(db, session.id, "sandbox_stopped", {})


def create_tool_execution(db: Session, session: SandboxSession, payload: dict[str, Any]) -> ToolExecution:
    tool_exec = ToolExecution(
        sandbox_id=session.id,
        tool_name=payload.get("tool_name"),
        command=payload.get("command", ""),
        input=payload.get("input", {}),
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(tool_exec)
    db.commit()
    db.refresh(tool_exec)

    publish_sandbox_event(
        db,
        session.id,
        "tool_started",
        {"tool": tool_exec.tool_name, "execution_id": str(tool_exec.id)},
    )

    try:
        timeout = payload.get("timeout_seconds") or settings.sandbox_default_timeout_seconds
        result = execute_tool(session.container_id, tool_exec.tool_name, tool_exec.input, timeout)

        tool_exec.output = result.get("output", {})
        tool_exec.stdout = result.get("stdout", "")
        tool_exec.stderr = result.get("stderr", "")
        tool_exec.duration_ms = result.get("duration_ms", 0.0)
        tool_exec.completed_at = datetime.now(timezone.utc)

        if result.get("exit_code") == 0:
            tool_exec.status = "completed"
            publish_sandbox_event(
                db,
                session.id,
                "tool_completed",
                {"tool": tool_exec.tool_name, "execution_id": str(tool_exec.id)},
            )
        else:
            tool_exec.status = "failed"
            publish_sandbox_event(
                db,
                session.id,
                "tool_failed",
                {"tool": tool_exec.tool_name, "execution_id": str(tool_exec.id), "stderr": tool_exec.stderr},
            )

        if tool_exec.stdout:
            artifact_service.persist_artifact(
                db,
                "tool_stdout",
                tool_exec.stdout.encode("utf-8"),
                f"{tool_exec.id}-stdout.txt",
                sandbox_id=session.id,
                workspace_id=session.workspace_id,
                tool_execution_id=tool_exec.id,
            )

        db.commit()
        db.refresh(tool_exec)
        return tool_exec

    except SandboxRuntimeError as exc:
        tool_exec.status = "failed"
        tool_exec.stderr = str(exc)
        tool_exec.completed_at = datetime.now(timezone.utc)
        db.commit()
        publish_sandbox_event(
            db,
            session.id,
            "tool_failed",
            {"tool": tool_exec.tool_name, "execution_id": str(tool_exec.id), "error": str(exc)},
        )
        raise


def list_tool_executions(db: Session, sandbox_id: UUID) -> list[ToolExecution]:
    return (
        db.query(ToolExecution)
        .filter(ToolExecution.sandbox_id == sandbox_id)
        .order_by(ToolExecution.created_at.desc())
        .all()
    )

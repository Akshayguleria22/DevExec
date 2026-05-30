from __future__ import annotations

import json
import logging
import time
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from app.core.config import settings

logger = logging.getLogger(__name__)


class SandboxRuntimeError(RuntimeError):
    pass


def _get_client() -> docker.DockerClient:
    return docker.from_env()


def start_container(workspace_mount: str | None, network_enabled: bool) -> str:
    try:
        client = _get_client()
        volumes = {}
        if workspace_mount:
            volumes[workspace_mount] = {"bind": "/workspace", "mode": "rw"}

        container = client.containers.run(
            image=settings.sandbox_image,
            command=["sleep", "infinity"],
            detach=True,
            network_mode="bridge" if network_enabled else "none",
            mem_limit=f"{settings.sandbox_memory_limit_mb}m",
            nano_cpus=int(settings.sandbox_cpu_limit * 1_000_000_000),
            pids_limit=settings.sandbox_pids_limit,
            security_opt=["no-new-privileges"],
            user=settings.sandbox_user,
            volumes=volumes,
            environment={"DEVEXEC_SANDBOX": "1"},
        )
        return container.id
    except DockerException as exc:
        raise SandboxRuntimeError(f"Failed to start sandbox container: {exc}") from exc


def stop_container(container_id: str) -> None:
    if not container_id:
        return
    try:
        client = _get_client()
        container = client.containers.get(container_id)
        container.stop(timeout=3)
        container.remove(force=True)
    except NotFound:
        return
    except DockerException as exc:
        logger.warning("Failed to stop sandbox container %s: %s", container_id, exc)


def execute_tool(
    container_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        client = _get_client()
        container = client.containers.get(container_id)
        command = [
            "python",
            "-m",
            "app.sandbox.runner",
            "--tool",
            tool_name,
            "--input",
            json.dumps(tool_input),
        ]

        start = time.time()
        exec_result = container.exec_run(command, stdout=True, stderr=True, demux=True, timeout=timeout_seconds)
        duration_ms = (time.time() - start) * 1000

        stdout_bytes, stderr_bytes = exec_result.output if exec_result.output else (b"", b"")
        stdout = (stdout_bytes or b"").decode("utf-8", errors="ignore")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="ignore")

        output_payload: dict[str, Any] = {}
        if stdout.strip():
            try:
                output_payload = json.loads(stdout)
            except json.JSONDecodeError:
                output_payload = {"raw": stdout.strip()}

        return {
            "exit_code": exec_result.exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "output": output_payload,
        }
    except DockerException as exc:
        raise SandboxRuntimeError(f"Sandbox execution failed: {exc}") from exc

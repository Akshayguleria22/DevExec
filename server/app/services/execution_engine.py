"""Execution Engine — hardened step runner with retry, validation, timing, and warnings.

Step Contract:
  Each step returns: {"success": bool, "data": ..., "error": ...}

Features:
  - Max 2 retry attempts per step (on exception or invalid output)
  - Per-tool output schema validation
  - Fallback output on total failure
  - Structured warnings for partial failures
  - Full timing: per-step and overall start_time, end_time, duration_ms
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.models.execution import ExecutionResult, StepResult
from app.services.planner import plan_task
from app.tools.registry import TOOLS, execute_tool

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

# Required output keys per tool for strict validation
REQUIRED_OUTPUT_KEYS: dict[str, set[str]] = {
    "api_test": {"target", "test_cases", "summary"},
    "log_analysis": {"error_type", "root_cause", "suggestion"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_valid_output(tool_name: str, output: Any) -> bool:
    """Enforce strict schema: output must be dict with all required keys for the tool."""
    if not isinstance(output, dict) or not output:
        return False

    required = REQUIRED_OUTPUT_KEYS.get(tool_name)
    if required is None:
        # Unknown tool — accept any non-empty dict
        return True

    return required.issubset(output.keys())


def _fallback_output(tool_name: str, error: str) -> dict[str, Any]:
    """Return a safe fallback output when a tool fails after all retries."""
    if tool_name == "api_test":
        return {
            "target": {"url": None, "method": None},
            "test_cases": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "latency_ms": 0},
            "failures": [],
            "error": f"Fallback output used: {error}",
        }

    if tool_name == "log_analysis":
        return {
            "error_type": "unknown",
            "confidence": 0,
            "root_cause": "Log analysis failed after retries.",
            "suggestion": "Review logs manually and retry with clearer context.",
            "error": f"Fallback output used: {error}",
        }

    return {"error": f"Fallback output used: {error}"}


def _make_step_contract(success: bool, data: Any = None, error: str | None = None) -> dict[str, Any]:
    """Enforce the strict step contract: {success, data, error}."""
    return {
        "success": success,
        "data": data,
        "error": error,
    }


def run_execution(task_input: str) -> dict[str, Any]:
    """Execute a planned sequence of tool steps with retry, validation, and full timing."""

    execution_start = _utc_now()
    plan = plan_task(task_input)
    logger.info("Execution plan created with %d step(s).", len(plan))

    result = ExecutionResult()
    result.start_time = execution_start.isoformat()

    for planned_step in plan:
        step_name = str(planned_step.get("tool", "unknown"))
        step_input = planned_step.get("input", {})

        step_start = _utc_now()
        step_status = "failed"
        step_output: dict[str, Any] | None = None
        step_error: str | None = None
        attempts_used = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts_used = attempt
            try:
                output = execute_tool(step_name, step_input)

                if not _is_valid_output(step_name, output):
                    raise ValueError(
                        f"Invalid output schema from tool '{step_name}': "
                        f"missing keys {REQUIRED_OUTPUT_KEYS.get(step_name, set()) - set(output.keys() if isinstance(output, dict) else [])}"
                    )

                step_output = output
                step_status = "completed"
                step_error = None

                if attempt > 1:
                    result.warnings.append(f"Step '{step_name}' succeeded on retry attempt {attempt}.")
                    result.total_retries += 1
                    logger.info("Step '%s' recovered on attempt %d.", step_name, attempt)

                break

            except Exception as exc:  # noqa: BLE001
                step_error = str(exc)
                logger.warning("Step '%s' failed on attempt %d: %s", step_name, attempt, step_error)

                if attempt < MAX_ATTEMPTS:
                    result.warnings.append(f"Step '{step_name}' failed on attempt {attempt}; retrying.")
                    continue

                # All retries exhausted
                step_output = _fallback_output(step_name, step_error)
                result.step_errors.append({"step": step_name, "error": step_error})
                result.warnings.append(f"Step '{step_name}' used fallback output after {MAX_ATTEMPTS} attempts.")
                result.total_retries += attempt - 1
                logger.error("Step '%s' exhausted all %d attempts.", step_name, MAX_ATTEMPTS)

        step_end = _utc_now()
        duration_ms = int((step_end - step_start).total_seconds() * 1000)

        step_result = StepResult(
            name=step_name,
            status=step_status,
            start_time=step_start.isoformat(),
            end_time=step_end.isoformat(),
            duration_ms=duration_ms,
            attempts=attempts_used,
            output=step_output,
            error=step_error,
        )
        result.steps.append(step_result)

    execution_end = _utc_now()
    result.end_time = execution_end.isoformat()
    result.duration_ms = int((execution_end - execution_start).total_seconds() * 1000)

    logger.info(
        "Execution completed in %dms — %d step(s), %d warning(s), %d error(s), %d retry(ies).",
        result.duration_ms,
        len(result.steps),
        len(result.warnings),
        len(result.step_errors),
        result.total_retries,
    )

    return result.to_dict()

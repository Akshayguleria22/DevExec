from datetime import datetime, timezone
from typing import Any

from app.services.planner import plan_task
from app.tools.registry import execute_tool

MAX_ATTEMPTS = 2
LOG_ANALYSIS_KEYS = {"error_type", "root_cause", "suggestion"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_valid_output(tool_name: str, output: Any) -> bool:
    if tool_name == "api_test":
        return isinstance(output, dict) and bool(output)

    if tool_name == "log_analysis":
        return isinstance(output, dict) and LOG_ANALYSIS_KEYS.issubset(output.keys())

    return isinstance(output, dict) and bool(output)


def _fallback_output(tool_name: str, error: str) -> dict[str, Any]:
    if tool_name == "api_test":
        return {
            "target": {"url": None, "method": None},
            "test_cases": [],
            "summary": {"total": 0, "passed": 0, "failed": 0},
            "error": f"Fallback output used: {error}",
        }

    if tool_name == "log_analysis":
        return {
            "error_type": "unknown",
            "root_cause": "Log analysis failed after retries.",
            "suggestion": "Review logs manually and retry with clearer context.",
            "error": f"Fallback output used: {error}",
        }

    return {"error": f"Fallback output used: {error}"}


def run_execution(task_input: str) -> dict[str, Any]:
    plan = plan_task(task_input)
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []
    step_errors: list[dict[str, str]] = []

    for planned_step in plan:
        step_name = str(planned_step.get("tool", "unknown"))
        step_input = planned_step.get("input", {})

        step_start = _utc_now()
        step_status = "failed"
        step_output: dict[str, Any] | None = None
        step_error: str | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                output = execute_tool(step_name, step_input)
                if not _is_valid_output(step_name, output):
                    raise ValueError(f"Invalid output from tool: {step_name}")

                step_output = output
                step_status = "completed"
                step_error = None

                if attempt > 1:
                    warnings.append(f"Step '{step_name}' succeeded on retry attempt {attempt}.")
                break
            except Exception as exc:  # noqa: BLE001
                step_error = str(exc)
                if attempt < MAX_ATTEMPTS:
                    warnings.append(f"Step '{step_name}' failed on attempt {attempt}; retrying.")
                    continue

                step_output = _fallback_output(step_name, step_error)
                step_errors.append({"step": step_name, "error": step_error})
                warnings.append(f"Step '{step_name}' used fallback output after retries.")

        step_end = _utc_now()
        duration_ms = int((step_end - step_start).total_seconds() * 1000)

        steps.append(
            {
                "name": step_name,
                "status": step_status,
                "start_time": step_start.isoformat(),
                "end_time": step_end.isoformat(),
                "duration": duration_ms,
                "output": step_output,
                "error": step_error,
            }
        )

    return {
        "steps": steps,
        "warnings": warnings,
        "step_errors": step_errors,
    }

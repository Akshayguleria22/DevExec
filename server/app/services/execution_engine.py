"""Execution Engine — hardened step runner with memory, regression detection, and observability.

Step Contract:
  Each step returns: {"success": bool, "data": ..., "error": ...}

Features:
  - Max 2 retry attempts per step (on exception or invalid output)
  - Per-tool output schema validation
  - Fallback output on total failure
  - Structured warnings for partial failures
  - Full timing: per-step and overall start_time, end_time, duration_ms
  - Execution memory: records every run for historical comparison
  - Regression detection: compares current vs previous run
  - Tool metrics: feeds per-tool performance counters
    - Execution event stream: emits persistent events for websocket replay
    - Enhanced output: execution + regression + analysis + events (+ comparison/tool_metrics)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.models.execution import ExecutionResult, StepResult
from app.services.event_stream import build_transient_event, publish_execution_event
from app.services.metrics_collector import metrics_collector
from app.services.planner import plan_task
from app.services.regression_detector import check_regression
from app.tools.registry import execute_tool

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

# Required output keys per tool for strict validation
REQUIRED_OUTPUT_KEYS: dict[str, set[str]] = {
    "api_test": {"target", "test_cases", "summary"},
    "log_analysis": {"error_type", "confidence", "root_cause", "suggestion"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_valid_output(tool_name: str, output: Any) -> bool:
    """Enforce strict schema: output must be dict with all required keys for the tool."""
    if not isinstance(output, dict) or not output:
        return False

    required = REQUIRED_OUTPUT_KEYS.get(tool_name)
    if required is None:
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


def _extract_run_metrics(result: ExecutionResult) -> dict[str, Any]:
    """Extract metrics from an execution result for memory and regression tracking."""
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    total_latency = 0.0

    for step in result.steps:
        if step.name == "api_test" and step.output:
            summary = step.output.get("summary", {})
            total_tests += summary.get("total", 0)
            passed_tests += summary.get("passed", 0)
            failed_tests += summary.get("failed", 0)
            total_latency += summary.get("latency_ms", 0.0)

    success_rate = round(passed_tests / total_tests * 100, 2) if total_tests > 0 else 0.0

    return {
        "success_rate": success_rate,
        "latency_ms": round(total_latency, 2),
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "total_retries": result.total_retries,
        "duration_ms": result.duration_ms,
    }


def _build_analysis(result: ExecutionResult) -> dict[str, Any]:
    log_findings = [
        step.output
        for step in result.steps
        if step.name == "log_analysis" and isinstance(step.output, dict)
    ]

    return {
        "primary_issue": log_findings[-1] if log_findings else None,
        "log_findings": log_findings,
        "warnings_count": len(result.warnings),
        "errors_count": len(result.step_errors),
    }


def _emit_event(
    events: list[dict[str, Any]],
    db_session: Any,
    task_uuid: UUID | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if db_session is not None and task_uuid is not None:
        event = publish_execution_event(db_session, task_uuid, event_type, payload)
    else:
        event = build_transient_event(
            str(task_uuid) if task_uuid else None,
            event_type,
            payload,
            seq=len(events) + 1,
        )
    events.append(event)


def run_execution(task_input: str, db_session: Any = None, task_id: str | UUID | None = None) -> dict[str, Any]:
    """Execute a planned sequence of tool steps with full observability.

    Args:
        task_input: Raw task input string.
        db_session: Optional SQLAlchemy session for memory/metrics persistence.
                    If None, memory and DB-based metrics are skipped.

    Returns:
        Enhanced output:
        {
            "execution": { steps, warnings, step_errors, timing },
            "regression": { regression: bool, details, flags },
            "analysis": { primary_issue, log_findings, warnings_count, errors_count },
            "events": [ ...execution events... ],
            "comparison": { current vs previous run },
            "tool_metrics": { per-tool stats },
        }
    """
    execution_start = _utc_now()
    plan = plan_task(task_input)
    logger.info("Execution plan created with %d step(s).", len(plan))

    task_uuid: UUID | None = None
    if task_id is not None:
        try:
            task_uuid = task_id if isinstance(task_id, UUID) else UUID(str(task_id))
        except ValueError:
            logger.warning("Invalid task_id received for event stream: %s", task_id)

    events: list[dict[str, Any]] = []
    _emit_event(
        events,
        db_session,
        task_uuid,
        "execution_started",
        {
            "plan": [step.get("tool", "unknown") for step in plan],
            "start_time": execution_start.isoformat(),
        },
    )

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

        _emit_event(
            events,
            db_session,
            task_uuid,
            "step_started",
            {
                "step": step_name,
                "start_time": step_start.isoformat(),
            },
        )

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

                _emit_event(
                    events,
                    db_session,
                    task_uuid,
                    "step_completed",
                    {
                        "step": step_name,
                        "attempt": attempt,
                        "status": "completed",
                    },
                )

                break

            except Exception as exc:  # noqa: BLE001
                step_error = str(exc)
                logger.warning("Step '%s' failed on attempt %d: %s", step_name, attempt, step_error)

                if attempt < MAX_ATTEMPTS:
                    result.warnings.append(f"Step '{step_name}' failed on attempt {attempt}; retrying.")
                    _emit_event(
                        events,
                        db_session,
                        task_uuid,
                        "step_retry",
                        {
                            "step": step_name,
                            "attempt": attempt,
                            "error": step_error,
                        },
                    )
                    continue

                step_output = _fallback_output(step_name, step_error)
                result.step_errors.append({"step": step_name, "error": step_error})
                result.warnings.append(f"Step '{step_name}' used fallback output after {MAX_ATTEMPTS} attempts.")
                result.total_retries += attempt - 1
                logger.error("Step '%s' exhausted all %d attempts.", step_name, MAX_ATTEMPTS)
                _emit_event(
                    events,
                    db_session,
                    task_uuid,
                    "step_error",
                    {
                        "step": step_name,
                        "attempt": attempt,
                        "error": step_error,
                    },
                )

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

        # Record tool metric (in-memory)
        metrics_collector.record_tool_execution(
            tool_name=step_name,
            duration_ms=duration_ms,
            success=(step_status == "completed"),
            attempts=attempts_used,
        )

    execution_end = _utc_now()
    result.end_time = execution_end.isoformat()
    result.duration_ms = int((execution_end - execution_start).total_seconds() * 1000)

    _emit_event(
        events,
        db_session,
        task_uuid,
        "execution_completed",
        {
            "end_time": execution_end.isoformat(),
            "duration_ms": result.duration_ms,
            "warnings": len(result.warnings),
            "errors": len(result.step_errors),
        },
    )

    logger.info(
        "Execution completed in %dms — %d step(s), %d warning(s), %d error(s), %d retry(ies).",
        result.duration_ms,
        len(result.steps),
        len(result.warnings),
        len(result.step_errors),
        result.total_retries,
    )

    # ---- Extract metrics for memory and regression ----
    run_metrics = _extract_run_metrics(result)
    execution_dict = result.to_dict()

    # ---- Memory + Regression (requires DB session) ----
    comparison: dict[str, Any] | None = None
    regression: dict[str, Any] | None = None

    if db_session is not None:
        try:
            from app.services.execution_memory import get_previous_run, record_run

            # Get previous run BEFORE recording current (so we compare with actual previous)
            prev_run = get_previous_run(db_session, task_input)

            # Record current run to memory
            record_run(
                db=db_session,
                task_id=str(task_uuid) if task_uuid else None,
                task_input=task_input,
                metrics=run_metrics,
                execution_trace=execution_dict,
            )

            # Regression detection
            prev_metrics = prev_run["metrics"] if prev_run else None
            regression = check_regression(run_metrics, prev_metrics)

            # Build comparison data
            if prev_run:
                comparison = {
                    "previous_run": {
                        "timestamp": prev_run.get("timestamp"),
                        "metrics": prev_run.get("metrics"),
                    },
                    "current_run": {
                        "timestamp": _utc_now().isoformat(),
                        "metrics": run_metrics,
                    },
                }
            else:
                comparison = {
                    "previous_run": None,
                    "current_run": {
                        "timestamp": _utc_now().isoformat(),
                        "metrics": run_metrics,
                    },
                    "note": "First run — no previous data for comparison.",
                }

            # Add regression warning to result if detected
            if regression and regression.get("regression"):
                flags_str = ", ".join(regression.get("flags", []))
                result.warnings.append(f"⚠ Regression detected: {flags_str}")
                execution_dict = result.to_dict()  # Re-serialize with warning

            # Flush tool metrics to DB
            metrics_collector.flush_to_db(db_session)

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to record memory/regression: %s", exc)

    # ---- Build enhanced output (Part 4) ----
    return {
        "execution": execution_dict,
        "analysis": _build_analysis(result),
        "events": events,
        "comparison": comparison,
        "regression": regression,
        "tool_metrics": metrics_collector.get_tool_metrics(),
    }

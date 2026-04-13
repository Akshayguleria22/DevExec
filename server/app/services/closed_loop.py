"""Closed-Loop Execution Service — diagnostic feedback loop with before/after comparison.

Flow:
  1. Run api_test with original input
  2. If failures exist → extract failing cases, pass to log_analysis
  3. log_analysis returns root cause + suggested fix
  4. Modify test conditions (simulate applying the fix)
  5. Re-run api_test with modified conditions
  6. Compare before vs after: success rate delta, latency delta
"""

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from app.tools.api_test import run_api_test
from app.tools.log_analysis import analyze_logs

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_failure_logs(api_result: dict[str, Any]) -> str:
    """Extract failure details from an api_test result as log text for analysis."""
    failures = api_result.get("failures", [])
    if not failures:
        # Fall back to checking test_cases directly
        failures = [
            {"name": tc["name"], "error": tc.get("error", "unknown")}
            for tc in api_result.get("test_cases", [])
            if tc.get("status") == "failed"
        ]

    if not failures:
        return ""

    log_lines = []
    for f in failures:
        name = f.get("name", "unknown_case")
        error = f.get("error") or "no error message"
        http_status = f.get("http_status")
        status_str = f" (HTTP {http_status})" if http_status else ""
        log_lines.append(f"[FAIL] {name}{status_str}: {error}")

    return "\n".join(log_lines)


def _apply_fix_to_input(
    original_input: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Simulate applying the suggested fix to the test input.

    Based on the error_type from analysis, modify the input to address the issue:
      - timeout: reduce request scope (remove heavy body)
      - auth_error: add placeholder auth header
      - validation_error: fix body structure
      - server_error: simplify request
      - unknown: no modification
    """
    modified = copy.deepcopy(original_input)
    error_type = analysis.get("error_type", "unknown")

    if error_type == "timeout":
        # Simulate fix: simplify payload to reduce server load
        modified["body"] = None
        if "headers" not in modified:
            modified["headers"] = {}
        modified["headers"]["X-Timeout-Budget"] = "extended"
        logger.info("Applied timeout fix: removed body, added timeout budget header.")

    elif error_type == "auth_error":
        # Simulate fix: add authorization header
        if "headers" not in modified:
            modified["headers"] = {}
        modified["headers"]["Authorization"] = "Bearer <corrected-token>"
        logger.info("Applied auth fix: added authorization header.")

    elif error_type == "validation_error":
        # Simulate fix: ensure body has required structure
        if modified.get("body") is None:
            modified["body"] = {}
        if isinstance(modified["body"], dict):
            modified["body"]["_fix_applied"] = True
        logger.info("Applied validation fix: ensured body structure.")

    elif error_type == "server_error":
        # Simulate fix: simplify request
        modified["body"] = None
        modified["method"] = "GET"
        logger.info("Applied server error fix: simplified request to GET with no body.")

    else:
        logger.info("No fix applied for error_type='%s'.", error_type)

    return modified


def _compute_improvement(
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
) -> dict[str, Any]:
    """Compute deltas between before and after runs."""
    before_total = before_summary.get("total", 0)
    after_total = after_summary.get("total", 0)

    before_passed = before_summary.get("passed", 0)
    after_passed = after_summary.get("passed", 0)

    before_rate = (before_passed / before_total * 100) if before_total > 0 else 0.0
    after_rate = (after_passed / after_total * 100) if after_total > 0 else 0.0

    before_latency = before_summary.get("latency_ms", 0)
    after_latency = after_summary.get("latency_ms", 0)

    return {
        "success_rate_before": round(before_rate, 2),
        "success_rate_after": round(after_rate, 2),
        "success_delta": round(after_rate - before_rate, 2),
        "latency_before_ms": before_latency,
        "latency_after_ms": after_latency,
        "latency_delta_ms": round(after_latency - before_latency, 2),
    }


def execute_closed_loop(task_input: dict[str, Any]) -> dict[str, Any]:
    """Run the full closed-loop diagnostic flow.

    Args:
        task_input: dict with keys: url, method, headers, body, (optional) logs

    Returns:
        {
            "before": {...api_test result...},
            "after": {...api_test result...},
            "improvement": {"success_delta": ..., "latency_delta_ms": ...},
            "analysis": {...log_analysis result...},
            "execution_trace": {
                "steps": [...],
                "start_time": ...,
                "end_time": ...,
                "duration_ms": ...,
            }
        }
    """
    trace_steps: list[dict[str, Any]] = []
    loop_start = _utc_now()

    # ---- Step 1: Run api_test (BEFORE) ----
    step1_start = _utc_now()
    logger.info("Closed-loop Step 1: Running initial api_test.")
    before_input = {
        "url": task_input.get("url", ""),
        "method": task_input.get("method", "GET"),
        "headers": task_input.get("headers", {}),
        "body": task_input.get("body"),
    }
    before_result = run_api_test(before_input)
    step1_end = _utc_now()
    trace_steps.append({
        "step": "api_test_before",
        "start_time": step1_start.isoformat(),
        "end_time": step1_end.isoformat(),
        "duration_ms": int((step1_end - step1_start).total_seconds() * 1000),
        "status": "completed",
    })

    before_summary = before_result.get("summary", {})
    before_failures = before_result.get("failures", [])

    # ---- Step 2 & 3: If failures, run log_analysis ----
    analysis_result: dict[str, Any] = {
        "error_type": "none",
        "confidence": 100,
        "root_cause": "All tests passed. No failures to analyze.",
        "suggestion": "No action needed.",
    }

    if before_summary.get("failed", 0) > 0 or before_failures:
        step2_start = _utc_now()
        logger.info("Closed-loop Step 2-3: Failures detected (%d), running log_analysis.", len(before_failures))

        failure_logs = _extract_failure_logs(before_result)

        # If the user provided explicit logs, combine them
        explicit_logs = task_input.get("logs")
        if explicit_logs and isinstance(explicit_logs, str):
            failure_logs = f"{explicit_logs}\n---\n{failure_logs}"

        analysis_result = analyze_logs({"logs": failure_logs})
        step2_end = _utc_now()
        trace_steps.append({
            "step": "log_analysis",
            "start_time": step2_start.isoformat(),
            "end_time": step2_end.isoformat(),
            "duration_ms": int((step2_end - step2_start).total_seconds() * 1000),
            "status": "completed",
            "input_log_length": len(failure_logs),
        })

    # ---- Step 4: Modify test conditions (simulate fix) ----
    step4_start = _utc_now()
    logger.info("Closed-loop Step 4: Applying fix for error_type='%s'.", analysis_result.get("error_type"))
    modified_input = _apply_fix_to_input(before_input, analysis_result)
    step4_end = _utc_now()
    trace_steps.append({
        "step": "apply_fix",
        "start_time": step4_start.isoformat(),
        "end_time": step4_end.isoformat(),
        "duration_ms": int((step4_end - step4_start).total_seconds() * 1000),
        "status": "completed",
        "error_type": analysis_result.get("error_type"),
    })

    # ---- Step 5: Re-run api_test (AFTER) ----
    step5_start = _utc_now()
    logger.info("Closed-loop Step 5: Running post-fix api_test.")
    after_result = run_api_test(modified_input)
    step5_end = _utc_now()
    trace_steps.append({
        "step": "api_test_after",
        "start_time": step5_start.isoformat(),
        "end_time": step5_end.isoformat(),
        "duration_ms": int((step5_end - step5_start).total_seconds() * 1000),
        "status": "completed",
    })

    after_summary = after_result.get("summary", {})

    # ---- Step 6: Compare results ----
    step6_start = _utc_now()
    improvement = _compute_improvement(before_summary, after_summary)
    step6_end = _utc_now()
    trace_steps.append({
        "step": "compare_results",
        "start_time": step6_start.isoformat(),
        "end_time": step6_end.isoformat(),
        "duration_ms": int((step6_end - step6_start).total_seconds() * 1000),
        "status": "completed",
    })

    loop_end = _utc_now()
    total_duration = int((loop_end - loop_start).total_seconds() * 1000)

    logger.info(
        "Closed-loop completed in %dms. Success delta: %+.1f%%, Latency delta: %+.1fms.",
        total_duration,
        improvement["success_delta"],
        improvement["latency_delta_ms"],
    )

    return {
        "before": before_result,
        "after": after_result,
        "improvement": improvement,
        "analysis": analysis_result,
        "execution_trace": {
            "steps": trace_steps,
            "start_time": loop_start.isoformat(),
            "end_time": loop_end.isoformat(),
            "duration_ms": total_duration,
        },
    }

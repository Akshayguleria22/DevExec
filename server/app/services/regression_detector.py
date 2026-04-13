"""Regression Detection — compares execution runs and flags performance degradation.

Provides:
  - compare_runs(): compare two run snapshots and detect regressions
  - check_regression(): one-call to compare current vs previous and return result

Detection criteria:
  - Drop in success_rate (any negative delta)
  - Increase in latency beyond threshold (> 20% increase)
  - Increase in failure count

Separated from execution engine and memory for clean architecture (Part 7).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds for regression detection
SUCCESS_RATE_DROP_THRESHOLD = 0.0  # Any drop flags a regression
LATENCY_INCREASE_THRESHOLD_PCT = 20.0  # Flag if latency increases by >20%
FAILURE_INCREASE_THRESHOLD = 0  # Any increase in failures flags a regression


def compare_runs(
    current_run: dict[str, Any],
    previous_run: dict[str, Any],
) -> dict[str, Any]:
    """Compare two execution run snapshots and detect regressions.

    Args:
        current_run: Dict with "metrics" key containing success_rate, latency_ms, failed_tests.
        previous_run: Dict with "metrics" key containing success_rate, latency_ms, failed_tests.

    Returns:
        {
            "regression": true/false,
            "details": {
                "success_rate_before": ...,
                "success_rate_after": ...,
                "success_delta": ...,
                "latency_before_ms": ...,
                "latency_after_ms": ...,
                "latency_delta_ms": ...,
                "latency_delta_pct": ...,
                "failures_before": ...,
                "failures_after": ...,
                "failure_delta": ...,
            },
            "flags": ["success_drop", "latency_increase", "failure_increase"]
        }
    """
    current_metrics = current_run.get("metrics", {})
    previous_metrics = previous_run.get("metrics", {})

    cur_success = current_metrics.get("success_rate", 0.0)
    prev_success = previous_metrics.get("success_rate", 0.0)
    success_delta = round(cur_success - prev_success, 2)

    cur_latency = current_metrics.get("latency_ms", 0.0)
    prev_latency = previous_metrics.get("latency_ms", 0.0)
    latency_delta = round(cur_latency - prev_latency, 2)
    latency_delta_pct = round((latency_delta / prev_latency * 100), 2) if prev_latency > 0 else 0.0

    cur_failures = current_metrics.get("failed_tests", 0)
    prev_failures = previous_metrics.get("failed_tests", 0)
    failure_delta = cur_failures - prev_failures

    # Evaluate regression flags
    flags: list[str] = []

    if success_delta < -SUCCESS_RATE_DROP_THRESHOLD and prev_success > 0:
        flags.append("success_drop")

    if latency_delta_pct > LATENCY_INCREASE_THRESHOLD_PCT and prev_latency > 0:
        flags.append("latency_increase")

    if failure_delta > FAILURE_INCREASE_THRESHOLD:
        flags.append("failure_increase")

    regression_detected = len(flags) > 0

    details = {
        "success_rate_before": prev_success,
        "success_rate_after": cur_success,
        "success_delta": success_delta,
        "latency_before_ms": prev_latency,
        "latency_after_ms": cur_latency,
        "latency_delta_ms": latency_delta,
        "latency_delta_pct": latency_delta_pct,
        "failures_before": prev_failures,
        "failures_after": cur_failures,
        "failure_delta": failure_delta,
    }

    if regression_detected:
        logger.warning(
            "Regression detected: flags=%s, success_delta=%.2f%%, latency_delta=%.1fms (%.1f%%).",
            flags,
            success_delta,
            latency_delta,
            latency_delta_pct,
        )
    else:
        logger.info("No regression detected. success_delta=%.2f%%, latency_delta=%.1fms.", success_delta, latency_delta)

    return {
        "regression": regression_detected,
        "details": details,
        "flags": flags,
    }


def check_regression(
    current_metrics: dict[str, Any],
    previous_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convenience wrapper: compare current metrics against a previous run.

    If no previous run exists, returns no regression.

    Args:
        current_metrics: success_rate, latency_ms, failed_tests, etc.
        previous_metrics: same shape, or None if this is the first run.

    Returns:
        Same format as compare_runs().
    """
    if previous_metrics is None:
        return {
            "regression": False,
            "details": {
                "success_rate_before": None,
                "success_rate_after": current_metrics.get("success_rate", 0.0),
                "success_delta": None,
                "latency_before_ms": None,
                "latency_after_ms": current_metrics.get("latency_ms", 0.0),
                "latency_delta_ms": None,
                "latency_delta_pct": None,
                "failures_before": None,
                "failures_after": current_metrics.get("failed_tests", 0),
                "failure_delta": None,
            },
            "flags": [],
            "note": "First run — no baseline for comparison.",
        }

    return compare_runs(
        {"metrics": current_metrics},
        {"metrics": previous_metrics},
    )

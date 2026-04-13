"""Log Analysis Tool — classifies errors and provides root cause analysis.

Error classifications:
  - timeout
  - auth_error
  - validation_error
  - server_error
  - unknown

Returns:
  {
    "error_type": "...",
    "confidence": 0-100,
    "root_cause": "...",
    "suggestion": "..."
  }
"""

import json
from typing import Any

# ---------------------------------------------------------------------------
# Signal definitions: (keyword/phrase → used for classification)
# ---------------------------------------------------------------------------

TIMEOUT_SIGNALS = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "connect timeout",
    "read timeout",
    "gateway timeout",
    "504",
    "request timed out",
)

AUTH_SIGNALS = (
    "unauthorized",
    "forbidden",
    "invalid token",
    "authentication failed",
    "auth error",
    "authentication error",
    "401",
    "403",
    "access denied",
    "permission denied",
    "token expired",
    "invalid credentials",
)

VALIDATION_SIGNALS = (
    "validation",
    "invalid payload",
    "schema",
    "missing required",
    "422",
    "bad request",
    "400",
    "unprocessable entity",
    "field required",
    "type error",
)

SERVER_ERROR_SIGNALS = (
    "internal server error",
    "500",
    "502",
    "503",
    "bad gateway",
    "service unavailable",
    "server error",
    "traceback",
    "exception",
    "segfault",
    "out of memory",
    "oom",
    "panic",
    "fatal",
)


def _extract_logs(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        logs = tool_input.get("logs", "")
        if isinstance(logs, str):
            return logs
        return json.dumps(logs)

    if isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
            if isinstance(parsed, dict) and "logs" in parsed:
                logs = parsed["logs"]
                if isinstance(logs, str):
                    return logs
                return json.dumps(logs)
        except json.JSONDecodeError:
            return tool_input
        return tool_input

    return ""


def _count_matches(text: str, signals: tuple[str, ...]) -> int:
    """Count how many distinct signals appear in the text."""
    return sum(1 for signal in signals if signal in text)


def _compute_confidence(match_count: int, total_signals: int) -> int:
    """Compute a confidence score (0-100) based on signal match density."""
    if match_count == 0:
        return 0
    # 1 match = 60, 2 = 75, 3+ = 85-95, scaling with signal set size
    base = 55
    per_match = min(match_count, 5) * 8
    confidence = min(base + per_match, 95)
    return confidence


def analyze_logs(tool_input: Any) -> dict[str, Any]:
    """Analyze log text and classify the error with a confidence score."""

    logs = _extract_logs(tool_input)

    if not logs.strip():
        return {
            "error_type": "unknown",
            "confidence": 0,
            "root_cause": "No logs were provided.",
            "suggestion": "Provide application logs that include error details.",
        }

    logs_lower = logs.lower()

    # Check each category and count matches
    classifications: list[tuple[str, int, tuple[str, ...], str, str]] = [
        (
            "timeout",
            _count_matches(logs_lower, TIMEOUT_SIGNALS),
            TIMEOUT_SIGNALS,
            "Service call exceeded expected response time.",
            "Check downstream availability, network latency, and timeout configuration.",
        ),
        (
            "auth_error",
            _count_matches(logs_lower, AUTH_SIGNALS),
            AUTH_SIGNALS,
            "Authentication or authorization failed for the request.",
            "Validate credentials, token expiry, and required access scopes.",
        ),
        (
            "validation_error",
            _count_matches(logs_lower, VALIDATION_SIGNALS),
            VALIDATION_SIGNALS,
            "Request payload did not satisfy validation rules.",
            "Review request schema and required fields before submitting.",
        ),
        (
            "server_error",
            _count_matches(logs_lower, SERVER_ERROR_SIGNALS),
            SERVER_ERROR_SIGNALS,
            "Server encountered an internal error while processing the request.",
            "Check server logs, resource limits, and recent deployments for breaking changes.",
        ),
    ]

    # Pick the classification with the most matches
    best_match = max(classifications, key=lambda c: c[1])
    error_type, match_count, signals, root_cause, suggestion = best_match

    if match_count == 0:
        return {
            "error_type": "unknown",
            "confidence": 15,
            "root_cause": "No known timeout, auth, validation, or server error signatures were detected.",
            "suggestion": "Inspect stack traces and correlated service logs for deeper context.",
        }

    confidence = _compute_confidence(match_count, len(signals))

    return {
        "error_type": error_type,
        "confidence": confidence,
        "root_cause": root_cause,
        "suggestion": suggestion,
    }

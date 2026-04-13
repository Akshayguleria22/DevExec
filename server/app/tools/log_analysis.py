import json
from typing import Any


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


def analyze_logs(tool_input: Any) -> dict[str, Any]:
    logs = _extract_logs(tool_input)

    if not logs.strip():
        return {
            "error_type": "unknown",
            "root_cause": "No logs were provided.",
            "suggestion": "Provide application logs that include error details.",
        }

    logs_lower = logs.lower()

    timeout_signals = ("timeout", "timed out", "deadline exceeded")
    auth_signals = (
        "unauthorized",
        "forbidden",
        "invalid token",
        "authentication failed",
        "auth error",
        "authentication error",
        "401",
        "403",
    )
    validation_signals = ("validation", "invalid payload", "schema", "missing required", "422", "bad request")

    if any(signal in logs_lower for signal in timeout_signals):
        return {
            "error_type": "timeout",
            "root_cause": "Service call exceeded expected response time.",
            "suggestion": "Check downstream availability, network latency, and timeout configuration.",
        }

    if any(signal in logs_lower for signal in auth_signals):
        return {
            "error_type": "auth_error",
            "root_cause": "Authentication or authorization failed for the request.",
            "suggestion": "Validate credentials, token expiry, and required access scopes.",
        }

    if any(signal in logs_lower for signal in validation_signals):
        return {
            "error_type": "validation_error",
            "root_cause": "Request payload did not satisfy validation rules.",
            "suggestion": "Review request schema and required fields before submitting.",
        }

    return {
        "error_type": "unknown",
        "root_cause": "No known timeout, auth, or validation signatures were detected.",
        "suggestion": "Inspect stack traces and correlated service logs for deeper context.",
    }

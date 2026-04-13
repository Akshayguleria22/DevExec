"""Task Planner — rule-based plan generation using tool registry metadata.

Determines which tools to run and in which order based on structured
or natural language task input.
"""

import json
import re
from typing import Any

from app.tools.registry import TOOLS

URL_PATTERN = re.compile(r"https?://[^\s\"']+")


def _get_supported_tools() -> set[str]:
    """Pull supported tool names from the registry instead of hardcoding."""
    return set(TOOLS.keys())


def _parse_structured_input(task_input: str) -> dict[str, Any]:
    try:
        parsed = json.loads(task_input)
    except (TypeError, json.JSONDecodeError):
        return {}

    if isinstance(parsed, dict):
        return parsed
    return {}


def _extract_url(raw_text: str, parsed: dict[str, Any]) -> str:
    parsed_url = parsed.get("url")
    if isinstance(parsed_url, str) and parsed_url.strip():
        return parsed_url.strip()

    match = URL_PATTERN.search(raw_text)
    if match:
        return match.group(0)

    return ""


def _normalize_method(parsed: dict[str, Any]) -> str:
    method = parsed.get("method", "GET")
    if isinstance(method, str):
        normalized = method.upper().strip()
        if normalized:
            return normalized
    return "GET"


def _sanitize_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    supported = _get_supported_tools()
    sanitized_plan: list[dict[str, Any]] = []

    for step in plan:
        tool_name = step.get("tool")
        step_input = step.get("input")

        if tool_name not in supported:
            continue

        if not isinstance(step_input, dict):
            step_input = {}

        sanitized_plan.append({"tool": tool_name, "input": step_input})

    if sanitized_plan:
        return sanitized_plan

    return [{"tool": "log_analysis", "input": {"logs": "No actionable input was detected."}}]


def plan_task(task_input: str) -> list[dict[str, Any]]:
    raw_input = task_input if isinstance(task_input, str) else str(task_input)
    lowered_input = raw_input.lower()
    parsed_input = _parse_structured_input(raw_input)

    should_run_api_test = "test" in lowered_input or any(
        key in parsed_input for key in ("url", "method", "headers", "body")
    )
    should_run_log_analysis = any(token in lowered_input for token in ("error", "logs", "log", "timeout")) or any(
        key in parsed_input for key in ("logs", "error")
    )

    plan: list[dict[str, Any]] = []

    if should_run_api_test:
        headers = parsed_input.get("headers") if isinstance(parsed_input.get("headers"), dict) else {}
        api_step_input: dict[str, Any] = {
            "url": _extract_url(raw_input, parsed_input),
            "method": _normalize_method(parsed_input),
            "headers": headers,
        }

        if "body" in parsed_input:
            api_step_input["body"] = parsed_input["body"]

        plan.append({"tool": "api_test", "input": api_step_input})

    if should_run_log_analysis:
        parsed_logs = parsed_input.get("logs")
        logs_value = parsed_logs if isinstance(parsed_logs, str) else raw_input
        plan.append({"tool": "log_analysis", "input": {"logs": logs_value}})

    return _sanitize_plan(plan)

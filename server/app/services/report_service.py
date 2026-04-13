import json
from typing import Any

from app.models.task import Task


def _safe_result(task: Task) -> dict[str, Any]:
    if isinstance(task.result, dict):
        return task.result
    return {}


def _safe_execution(task: Task) -> dict[str, Any]:
    result = _safe_result(task)
    execution = result.get("execution", {})
    if isinstance(execution, dict):
        return execution
    return {}


def build_task_summary(task: Task) -> dict[str, Any]:
    execution = _safe_execution(task)
    steps = execution.get("steps", []) if isinstance(execution.get("steps"), list) else []

    return {
        "task_id": str(task.id),
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "steps_total": len(steps),
        "steps_failed": len(task.step_errors or []),
        "duration_ms": execution.get("duration_ms", 0),
        "total_retries": execution.get("total_retries", task.retry_count),
    }


def _extract_failures(task: Task) -> list[dict[str, Any]]:
    execution = _safe_execution(task)
    steps = execution.get("steps", []) if isinstance(execution.get("steps"), list) else []

    failures: list[dict[str, Any]] = []

    for step_error in task.step_errors or []:
        failures.append(
            {
                "source": "step_error",
                "step": step_error.get("step"),
                "error": step_error.get("error"),
            }
        )

    for step in steps:
        if not isinstance(step, dict):
            continue

        if step.get("status") == "failed":
            failures.append(
                {
                    "source": "step_status",
                    "step": step.get("name"),
                    "error": step.get("error"),
                }
            )

        if step.get("name") == "api_test":
            output = step.get("output") or {}
            tool_failures = output.get("failures", []) if isinstance(output, dict) else []
            if isinstance(tool_failures, list):
                for tool_failure in tool_failures:
                    if isinstance(tool_failure, dict):
                        failures.append(
                            {
                                "source": "api_test",
                                "step": step.get("name"),
                                "error": tool_failure.get("error"),
                                "case": tool_failure.get("name"),
                                "http_status": tool_failure.get("http_status"),
                            }
                        )
                    else:
                        failures.append(
                            {
                                "source": "api_test",
                                "step": step.get("name"),
                                "error": str(tool_failure),
                            }
                        )

    return failures


def _extract_suggested_fixes(task: Task) -> list[str]:
    result = _safe_result(task)
    analysis = result.get("analysis", {}) if isinstance(result.get("analysis"), dict) else {}

    suggestions: list[str] = []

    primary_issue = analysis.get("primary_issue", {}) if isinstance(analysis.get("primary_issue"), dict) else {}
    primary_suggestion = primary_issue.get("suggestion")
    if isinstance(primary_suggestion, str) and primary_suggestion.strip():
        suggestions.append(primary_suggestion.strip())

    log_findings = analysis.get("log_findings", []) if isinstance(analysis.get("log_findings"), list) else []
    for finding in log_findings:
        if isinstance(finding, dict):
            suggestion = finding.get("suggestion")
            if isinstance(suggestion, str) and suggestion.strip():
                suggestions.append(suggestion.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        if suggestion not in seen:
            deduped.append(suggestion)
            seen.add(suggestion)

    return deduped


def build_task_report(task: Task) -> dict[str, Any]:
    result = _safe_result(task)
    execution = _safe_execution(task)

    metrics: dict[str, Any] = {
        "task_metrics": task.metrics or {},
        "execution_metrics": {
            "duration_ms": execution.get("duration_ms", 0),
            "total_retries": execution.get("total_retries", task.retry_count),
            "warnings": len(task.warnings or []),
            "step_errors": len(task.step_errors or []),
        },
        "tool_metrics": result.get("tool_metrics", {}),
    }

    report = {
        "summary": build_task_summary(task),
        "failures": _extract_failures(task),
        "regression": result.get("regression"),
        "suggested_fixes": _extract_suggested_fixes(task),
        "metrics": metrics,
    }

    return report


def build_task_markdown_report(task: Task) -> str:
    report = build_task_report(task)
    summary = report.get("summary", {})
    failures = report.get("failures", [])
    regression = report.get("regression") or {}
    suggestions = report.get("suggested_fixes", [])
    metrics = report.get("metrics", {})

    lines: list[str] = []
    lines.append(f"# DevExec Sentinel Report - Task {summary.get('task_id')}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Status: {summary.get('status')}")
    lines.append(f"- Steps: {summary.get('steps_total')} total / {summary.get('steps_failed')} failed")
    lines.append(f"- Duration: {summary.get('duration_ms')} ms")
    lines.append(f"- Retries: {summary.get('total_retries')}")
    lines.append("")

    lines.append("## Failures")
    if failures:
        for failure in failures:
            lines.append(
                f"- [{failure.get('source')}] step={failure.get('step')} case={failure.get('case')} error={failure.get('error')}"
            )
    else:
        lines.append("- No failures detected.")
    lines.append("")

    lines.append("## Regression")
    if isinstance(regression, dict):
        lines.append(f"- Regression detected: {regression.get('regression')}")
        flags = regression.get("flags", [])
        if isinstance(flags, list) and flags:
            lines.append(f"- Flags: {', '.join(str(flag) for flag in flags)}")
    else:
        lines.append("- No regression data available.")
    lines.append("")

    lines.append("## Suggested Fixes")
    if suggestions:
        for suggestion in suggestions:
            lines.append(f"- {suggestion}")
    else:
        lines.append("- No suggested fixes.")
    lines.append("")

    lines.append("## Metrics")
    lines.append(f"- Execution metrics: `{json.dumps(metrics.get('execution_metrics', {}), ensure_ascii=True)}`")
    lines.append(f"- Task metrics: `{json.dumps(metrics.get('task_metrics', {}), ensure_ascii=True)}`")

    return "\n".join(lines)

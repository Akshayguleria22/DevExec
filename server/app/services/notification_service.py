import json
import logging
from typing import Any

import requests

from app.core.config import settings
from app.models.task import Task
from app.services.report_service import build_task_markdown_report, build_task_report, build_task_summary

logger = logging.getLogger(__name__)


def _parse_task_input(task: Task) -> dict[str, Any]:
    if isinstance(task.input, dict):
        return task.input

    if not isinstance(task.input, str):
        return {}

    try:
        parsed = json.loads(task.input)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        pass
    return {}


def _send_webhook_message(event_type: str, payload: dict[str, Any]) -> None:
    if not settings.notification_webhook_url:
        return

    try:
        response = requests.post(
            settings.notification_webhook_url,
            json={"event_type": event_type, "payload": payload},
            timeout=settings.notification_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to send notification webhook '%s': %s", event_type, exc)


def _post_github_pr_comment(task: Task, markdown_report: str) -> None:
    if not settings.enable_github_pr_comment or not settings.github_token:
        return

    task_input = _parse_task_input(task)
    github_context = task_input.get("github") if isinstance(task_input.get("github"), dict) else {}

    repo_name = github_context.get("repository") or task_input.get("repo_name")
    pr_number = github_context.get("pr_number")

    if not repo_name or pr_number is None:
        return

    comment_body = "## DevExec Sentinel Execution Report\n\n" + markdown_report
    api_url = f"{settings.github_api_base_url.rstrip('/')}/repos/{repo_name}/issues/{pr_number}/comments"

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            api_url,
            headers=headers,
            json={"body": comment_body[:65000]},
            timeout=settings.notification_timeout_seconds,
        )
        response.raise_for_status()
        logger.info("Posted GitHub PR comment for task %s on %s#%s.", task.id, repo_name, pr_number)
    except requests.RequestException as exc:
        logger.warning("Failed to post GitHub PR comment for task %s: %s", task.id, exc)


def send_task_notifications(task: Task) -> None:
    report = build_task_report(task)
    summary = build_task_summary(task)
    markdown_report = build_task_markdown_report(task)

    if task.status == "completed":
        _send_webhook_message(
            "task_completed",
            {
                "task_id": str(task.id),
                "summary": summary,
            },
        )

    if task.status == "failed" or bool(report.get("failures")):
        _send_webhook_message(
            "failure_detected",
            {
                "task_id": str(task.id),
                "summary": summary,
                "failures": report.get("failures", []),
            },
        )

    regression = report.get("regression")
    if isinstance(regression, dict) and regression.get("regression"):
        _send_webhook_message(
            "regression_detected",
            {
                "task_id": str(task.id),
                "summary": summary,
                "regression": regression,
            },
        )

    _post_github_pr_comment(task, markdown_report)

import json
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.deployment_event import DeploymentEvent

DISCOVERY_TIMEOUT_SECONDS = 8


def _normalize_base_url(api_base_url: str) -> str:
    return api_base_url.rstrip("/")


def _extract_branch_from_ref(ref: str | None) -> str:
    if not isinstance(ref, str) or not ref.strip():
        return ""

    if ref.startswith("refs/heads/"):
        return ref.replace("refs/heads/", "", 1)

    return ref.split("/")[-1]


def parse_github_webhook_payload(
    payload: dict[str, Any],
    github_event: str | None,
    default_api_base_url: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    repo_name = repository.get("full_name") or repository.get("name")

    if not isinstance(repo_name, str) or not repo_name.strip():
        raise ValueError("Could not extract repository from webhook payload")

    event_name = github_event or payload.get("event")
    branch = ""
    commit_sha: str | None = None
    pr_number: int | None = None

    if event_name in {"pull_request", "pull_request_target"}:
        pull_request = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
        head = pull_request.get("head") if isinstance(pull_request.get("head"), dict) else {}

        branch = head.get("ref") if isinstance(head.get("ref"), str) else _extract_branch_from_ref(payload.get("ref"))
        commit_sha = head.get("sha") if isinstance(head.get("sha"), str) else payload.get("after")

        if isinstance(pull_request.get("number"), int):
            pr_number = pull_request.get("number")
        elif isinstance(payload.get("number"), int):
            pr_number = payload.get("number")
    else:
        branch = _extract_branch_from_ref(payload.get("ref"))
        commit_sha = payload.get("after") if isinstance(payload.get("after"), str) else None

        head_commit = payload.get("head_commit") if isinstance(payload.get("head_commit"), dict) else {}
        if commit_sha is None and isinstance(head_commit.get("id"), str):
            commit_sha = head_commit.get("id")

    if not branch:
        fallback_branch = payload.get("branch")
        if isinstance(fallback_branch, str) and fallback_branch.strip():
            branch = fallback_branch.strip()

    if not branch:
        branch = "unknown"

    api_base_url = payload.get("api_base_url")
    if not isinstance(api_base_url, str) or not api_base_url.strip():
        deployment = payload.get("deployment") if isinstance(payload.get("deployment"), dict) else {}
        deployment_api_base_url = deployment.get("api_base_url")
        if isinstance(deployment_api_base_url, str) and deployment_api_base_url.strip():
            api_base_url = deployment_api_base_url

    if not isinstance(api_base_url, str) or not api_base_url.strip():
        homepage = repository.get("homepage")
        if isinstance(homepage, str) and homepage.strip():
            api_base_url = homepage

    if (not isinstance(api_base_url, str) or not api_base_url.strip()) and default_api_base_url:
        api_base_url = default_api_base_url

    if not isinstance(api_base_url, str) or not api_base_url.strip():
        raise ValueError("Missing api_base_url in webhook payload and DEFAULT_API_BASE_URL is not configured")

    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    github_context = {
        "event": event_name,
        "repository": repo_name,
        "branch": branch,
        "commit_sha": commit_sha,
        "pr_number": pr_number,
        "sender": sender.get("login") if isinstance(sender.get("login"), str) else None,
    }

    deploy_request = {
        "repo_name": repo_name,
        "branch": branch,
        "commit_sha": commit_sha,
        "api_base_url": api_base_url,
        "expand_endpoints": bool(payload.get("expand_endpoints", False)),
    }

    return deploy_request, github_context


def discover_endpoints(api_base_url: str) -> tuple[list[str], list[str]]:
    base = _normalize_base_url(api_base_url)
    warnings: list[str] = []

    discovery_docs = [
        f"{base}/openapi.json",
        f"{base}/swagger.json",
    ]

    for doc_url in discovery_docs:
        try:
            response = requests.get(doc_url, timeout=DISCOVERY_TIMEOUT_SECONDS)
            if response.status_code >= 400:
                continue

            payload = response.json()
            paths = payload.get("paths", {}) if isinstance(payload, dict) else {}
            if not isinstance(paths, dict):
                continue

            endpoints = sorted(path for path in paths.keys() if isinstance(path, str) and path.startswith("/"))
            if endpoints:
                return endpoints, warnings
        except (requests.RequestException, ValueError):
            continue

    warnings.append("Could not discover endpoints from OpenAPI docs; defaulting to base URL only.")
    return [], warnings


def _build_endpoint_urls(api_base_url: str, endpoints: list[str]) -> list[str]:
    base = _normalize_base_url(api_base_url)
    return [urljoin(f"{base}/", endpoint.lstrip("/")) for endpoint in endpoints]


def generate_task_input(
    repo_name: str,
    branch: str,
    api_base_url: str,
    commit_sha: str | None,
    github_context: dict[str, Any] | None,
    expand_endpoints: bool,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    generated_task = f"Test all endpoints for {api_base_url}"
    endpoints: list[str] = []
    warnings: list[str] = []

    if expand_endpoints:
        endpoints, discovery_warnings = discover_endpoints(api_base_url)
        warnings.extend(discovery_warnings)

    endpoint_urls = _build_endpoint_urls(api_base_url, endpoints) if endpoints else []

    task_input: dict[str, Any] = {
        "instruction": generated_task,
        "repo_name": repo_name,
        "branch": branch,
        "commit_sha": commit_sha,
        "api_base_url": _normalize_base_url(api_base_url),
        "url": _normalize_base_url(api_base_url),
        "method": "GET",
        "endpoints": endpoints,
        "endpoint_urls": endpoint_urls,
        "logs": json.dumps(
            {
                "deployment": {
                    "repo_name": repo_name,
                    "branch": branch,
                    "commit_sha": commit_sha,
                    "api_base_url": _normalize_base_url(api_base_url),
                }
            }
        ),
    }

    if isinstance(github_context, dict) and github_context:
        task_input["github"] = github_context

    return task_input, generated_task, endpoints, warnings


def create_deployment_event(
    db: Session,
    repo_name: str,
    branch: str,
    api_base_url: str,
    commit_sha: str | None,
    task_id: UUID,
    generated_task_input: dict[str, Any],
    endpoints: list[str],
) -> DeploymentEvent:
    event = DeploymentEvent(
        repo_name=repo_name,
        branch=branch,
        api_base_url=_normalize_base_url(api_base_url),
        commit_sha=commit_sha,
        task_id=task_id,
        generated_task_input=generated_task_input,
        discovered_endpoints=endpoints,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def find_existing_task_for_deployment(
    db: Session,
    repo_name: str,
    commit_sha: str | None,
    api_base_url: str,
) -> UUID | None:
    if not commit_sha:
        return None

    try:
        existing = (
            db.query(DeploymentEvent)
            .filter(
                DeploymentEvent.repo_name == repo_name,
                DeploymentEvent.commit_sha == commit_sha,
                DeploymentEvent.api_base_url == _normalize_base_url(api_base_url),
            )
            .order_by(desc(DeploymentEvent.created_at))
            .first()
        )
    except Exception:
        db.rollback()
        return None

    return existing.task_id if existing is not None else None

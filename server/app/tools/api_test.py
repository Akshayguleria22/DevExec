"""API Test Tool — runs endpoint tests and returns structured results.

Test categories:
  - valid_request: Tests with the provided payload as-is.
  - missing_fields: Tests with required fields removed.
  - invalid_types: Tests with wrong types for every field.

Returns:
  {
    "target": {"url": ..., "method": ...},
    "test_cases": [...],
    "summary": {"total": N, "passed": N, "failed": N, "latency_ms": N},
    "failures": [...]
  }
"""

import json
import time
from typing import Any
from urllib.parse import urljoin

import requests

REQUEST_TIMEOUT = (5, 15)  # (connect_timeout, read_timeout)
SUPPORTED_METHODS = {"GET", "POST"}


def _parse_input(tool_input: Any) -> dict[str, Any]:
    if isinstance(tool_input, dict):
        return tool_input

    if isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
        except json.JSONDecodeError as exc:
            raise ValueError("api_test requires JSON input with at least a 'url' field.") from exc

        if not isinstance(parsed, dict):
            raise ValueError("api_test JSON input must be an object.")
        return parsed

    raise ValueError("api_test input must be a JSON object or JSON string.")


def _validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    url = payload.get("url")
    method = payload.get("method", "GET")
    headers = payload.get("headers", {})

    if not isinstance(url, str) or not url.strip():
        errors.append("url is required and must be a non-empty string")

    if not isinstance(method, str) or method.upper() not in SUPPORTED_METHODS:
        errors.append(f"method must be one of {', '.join(sorted(SUPPORTED_METHODS))}")

    if headers is None:
        headers = {}
    if not isinstance(headers, dict):
        errors.append("headers must be an object")

    return errors


def _send_request(method: str, url: str, headers: dict[str, str], body: Any) -> tuple[int, float]:
    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": REQUEST_TIMEOUT,
    }

    if body is not None:
        if isinstance(body, (dict, list)):
            request_kwargs["json"] = body
        else:
            request_kwargs["data"] = body

    start = time.perf_counter()
    response = requests.request(**request_kwargs)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return response.status_code, latency_ms


def _build_target_urls(payload: dict[str, Any]) -> list[str]:
    endpoint_urls = payload.get("endpoint_urls")
    if isinstance(endpoint_urls, list):
        urls = [u.strip() for u in endpoint_urls if isinstance(u, str) and u.strip()]
        if urls:
            return urls

    api_base_url = payload.get("api_base_url")
    endpoints = payload.get("endpoints")
    if isinstance(api_base_url, str) and api_base_url.strip() and isinstance(endpoints, list):
        built_urls: list[str] = []
        for endpoint in endpoints:
            if isinstance(endpoint, str) and endpoint.strip():
                full_url = urljoin(f"{api_base_url.rstrip('/')}/", endpoint.lstrip("/"))
                built_urls.append(full_url)
        if built_urls:
            return built_urls

    url = payload.get("url")
    if isinstance(url, str) and url.strip():
        return [url.strip()]

    return []


def _generate_test_cases(base_payload: dict[str, Any], target_urls: list[str]) -> list[tuple[str, dict[str, Any], bool, str]]:
    """Generate test cases per target: valid request, missing fields, invalid types."""
    cases: list[tuple[str, dict[str, Any], bool, str]] = []

    resolved_targets = target_urls if target_urls else [str(base_payload.get("url", ""))]

    for target_url in resolved_targets:
        valid_payload = dict(base_payload)
        valid_payload["url"] = target_url
        cases.append(("valid_request", valid_payload, False, target_url))

        missing_payload = {
            "method": base_payload.get("method"),
            "headers": base_payload.get("headers"),
            "body": base_payload.get("body"),
        }
        cases.append(("missing_fields", missing_payload, True, target_url))

        invalid_types_payload = {
            "url": 123,
            "method": 456,
            "headers": "invalid",
            "body": base_payload.get("body"),
        }
        cases.append(("invalid_types", invalid_types_payload, True, target_url))

    return cases


def _run_single_case(
    case_name: str,
    case_payload: dict[str, Any],
    expects_failure: bool,
    target_url: str,
) -> dict[str, Any]:
    """Execute a single test case and return the structured result."""

    case_errors = _validate_payload(case_payload)

    if case_errors:
        case_passed = expects_failure
        return {
            "name": case_name,
            "target_url": target_url,
            "status": "passed" if case_passed else "failed",
            "latency_ms": 0,
            "http_status": None,
            "error": "; ".join(case_errors),
        }

    try:
        http_status, latency_ms = _send_request(
            method=str(case_payload.get("method")).upper(),
            url=str(case_payload.get("url")),
            headers=case_payload.get("headers", {}),
            body=case_payload.get("body"),
        )
        if expects_failure:
            case_passed = http_status >= 400
        else:
            case_passed = http_status < 400
        return {
            "name": case_name,
            "target_url": target_url,
            "status": "passed" if case_passed else "failed",
            "latency_ms": latency_ms,
            "http_status": http_status,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "name": case_name,
            "target_url": target_url,
            "status": "failed",
            "latency_ms": 0,
            "http_status": None,
            "error": str(exc),
        }


def run_api_test(tool_input: Any) -> dict[str, Any]:
    """Execute a suite of dynamic API tests and return structured results."""

    payload = _parse_input(tool_input)

    base_payload: dict[str, Any] = {
        "url": payload.get("url", ""),
        "api_base_url": payload.get("api_base_url", ""),
        "method": str(payload.get("method", "GET")).upper(),
        "headers": payload.get("headers") if isinstance(payload.get("headers"), dict) else {},
        "body": payload.get("body"),
        "endpoints": payload.get("endpoints") if isinstance(payload.get("endpoints"), list) else [],
        "endpoint_urls": payload.get("endpoint_urls") if isinstance(payload.get("endpoint_urls"), list) else [],
    }

    target_urls = _build_target_urls(base_payload)
    generated_cases = _generate_test_cases(base_payload, target_urls)
    test_cases: list[dict[str, Any]] = []

    for case_name, case_payload, expects_failure, target_url in generated_cases:
        result = _run_single_case(case_name, case_payload, expects_failure, target_url)
        test_cases.append(result)

    passed_count = sum(1 for case in test_cases if case["status"] == "passed")
    failed_count = len(test_cases) - passed_count
    total_latency = round(sum(case.get("latency_ms", 0) for case in test_cases), 2)

    failures = [
        {"name": c["name"], "http_status": c["http_status"], "error": c["error"]}
        for c in test_cases
        if c["status"] == "failed"
    ]

    return {
        "target": {
            "url": base_payload.get("url") or base_payload.get("api_base_url"),
            "method": base_payload.get("method"),
        },
        "targets": target_urls,
        "test_cases": test_cases,
        "summary": {
            "total": len(test_cases),
            "passed": passed_count,
            "failed": failed_count,
            "latency_ms": total_latency,
        },
        "failures": failures,
    }

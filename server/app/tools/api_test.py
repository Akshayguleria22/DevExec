import json
import time
from typing import Any

import requests

REQUEST_TIMEOUT_SECONDS = 15
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
        errors.append("method must be either GET or POST")

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
        "timeout": REQUEST_TIMEOUT_SECONDS,
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


def run_api_test(tool_input: Any) -> dict[str, Any]:
    payload = _parse_input(tool_input)

    base_payload: dict[str, Any] = {
        "url": payload.get("url", ""),
        "method": str(payload.get("method", "GET")).upper(),
        "headers": payload.get("headers") if isinstance(payload.get("headers"), dict) else {},
        "body": payload.get("body"),
    }

    test_inputs = [
        ("valid_request", base_payload),
        (
            "missing_fields",
            {
                "method": base_payload.get("method"),
                "headers": base_payload.get("headers"),
                "body": base_payload.get("body"),
            },
        ),
        (
            "invalid_types",
            {
                "url": 123,
                "method": 456,
                "headers": "invalid",
                "body": base_payload.get("body"),
            },
        ),
    ]

    test_cases: list[dict[str, Any]] = []

    for case_name, case_payload in test_inputs:
        case_errors = _validate_payload(case_payload)
        expected_failure = case_name in {"missing_fields", "invalid_types"}

        if case_errors:
            case_passed = expected_failure
            test_cases.append(
                {
                    "name": case_name,
                    "status": "passed" if case_passed else "failed",
                    "latency_ms": 0,
                    "http_status": None,
                    "error": "; ".join(case_errors),
                }
            )
            continue

        try:
            http_status, latency_ms = _send_request(
                method=str(case_payload.get("method")).upper(),
                url=str(case_payload.get("url")),
                headers=case_payload.get("headers", {}),
                body=case_payload.get("body"),
            )
            case_passed = (http_status < 400) if not expected_failure else (http_status >= 400)
            test_cases.append(
                {
                    "name": case_name,
                    "status": "passed" if case_passed else "failed",
                    "latency_ms": latency_ms,
                    "http_status": http_status,
                    "error": None,
                }
            )
        except requests.RequestException as exc:
            test_cases.append(
                {
                    "name": case_name,
                    "status": "failed",
                    "latency_ms": 0,
                    "http_status": None,
                    "error": str(exc),
                }
            )

    passed_count = sum(1 for case in test_cases if case["status"] == "passed")
    failed_count = len(test_cases) - passed_count

    return {
        "target": {
            "url": base_payload.get("url"),
            "method": base_payload.get("method"),
        },
        "test_cases": test_cases,
        "summary": {
            "total": len(test_cases),
            "passed": passed_count,
            "failed": failed_count,
        },
    }

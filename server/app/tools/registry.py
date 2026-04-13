"""Tool Registry — centralized registration with metadata for extensibility.

Each tool entry includes:
  - handler: the callable
  - description: what the tool does
  - input_keys: expected input keys (for documentation/validation)
  - output_keys: expected output keys (for schema validation)
  - version: tool version string
"""

from typing import Any, Callable

from app.tools.api_test import run_api_test
from app.tools.log_analysis import analyze_logs

ToolHandler = Callable[[Any], dict[str, Any]]


class ToolMeta:
    """Metadata descriptor for a registered tool."""

    __slots__ = ("handler", "description", "input_keys", "output_keys", "version")

    def __init__(
        self,
        handler: ToolHandler,
        description: str,
        input_keys: tuple[str, ...],
        output_keys: tuple[str, ...],
        version: str = "1.0.0",
    ):
        self.handler = handler
        self.description = description
        self.input_keys = input_keys
        self.output_keys = output_keys
        self.version = version


TOOLS: dict[str, ToolMeta] = {
    "api_test": ToolMeta(
        handler=run_api_test,
        description="Executes dynamic API test suites against a target URL.",
        input_keys=("url", "method", "headers", "body"),
        output_keys=("target", "test_cases", "summary", "failures"),
        version="2.0.0",
    ),
    "log_analysis": ToolMeta(
        handler=analyze_logs,
        description="Classifies errors from log text and provides root cause analysis.",
        input_keys=("logs",),
        output_keys=("error_type", "confidence", "root_cause", "suggestion"),
        version="2.0.0",
    ),
}


def execute_tool(name: str, tool_input: Any) -> dict[str, Any]:
    """Look up and execute a registered tool by name."""
    meta = TOOLS.get(name)
    if meta is None:
        raise ValueError(f"Unsupported tool: {name}")
    return meta.handler(tool_input)


def get_tool_meta(name: str) -> ToolMeta | None:
    """Retrieve metadata for a registered tool."""
    return TOOLS.get(name)


def list_tools() -> list[dict[str, Any]]:
    """Return a summary of all registered tools (for API/CI consumption)."""
    return [
        {
            "name": name,
            "description": meta.description,
            "input_keys": list(meta.input_keys),
            "output_keys": list(meta.output_keys),
            "version": meta.version,
        }
        for name, meta in TOOLS.items()
    ]

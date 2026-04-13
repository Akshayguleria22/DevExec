from typing import Any, Callable

from app.tools.api_test import run_api_test
from app.tools.log_analysis import analyze_logs

TOOLS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "api_test": run_api_test,
    "log_analysis": analyze_logs,
}


def execute_tool(name: str, tool_input: Any) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        raise ValueError(f"Unsupported tool: {name}")
    return tool(tool_input)

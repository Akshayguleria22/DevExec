from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    results: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    step_errors: list[dict[str, str]] = field(default_factory=list)

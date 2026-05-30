from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langgraph.graph import END, StateGraph

from app.models.agent import Agent
from app.models.agent_execution import AgentExecution
from app.models.execution_artifact import ExecutionArtifact
from app.models.tool_invocation import ToolInvocation
from app.services import agent_service
from app.services import sandbox_service
from app.services.agent_event_stream import publish_agent_event
from app.services.metrics_collector import metrics_collector
from app.services.planner import plan_task

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_policy(agent: Agent) -> dict[str, Any]:
    return {
        "max_retries": agent.execution_policy.get("max_retries", 1),
        "max_steps": agent.execution_policy.get("max_steps", 8),
        "allow_delegate": agent.execution_policy.get("allow_delegate", False),
    }


def _build_plan(agent: Agent, objective: str, allowed_tools: set[str]) -> list[dict[str, Any]]:
    if agent.agent_type == "coordinator":
        return [
            {"tool": "delegate", "input": {"agent_type": "diagnostic", "objective": objective}},
            {"tool": "delegate", "input": {"agent_type": "api_testing", "objective": objective}},
            {"tool": "delegate", "input": {"agent_type": "deployment_investigation", "objective": objective}},
        ]

    if agent.agent_type == "api_testing":
        return [{"tool": "api_test", "input": {"url": objective}}] if "api_test" in allowed_tools else []

    if agent.agent_type == "deployment_investigation":
        steps = [
            {"tool": "log_analysis", "input": {"logs": objective}},
            {"tool": "api_test", "input": {"url": objective}},
        ]
        return [step for step in steps if step["tool"] in allowed_tools]

    if agent.agent_type == "browser_automation":
        return [{"tool": "api_test", "input": {"url": objective}}] if "api_test" in allowed_tools else []

    if agent.agent_type == "diagnostic":
        planned = plan_task(objective)
        return [step for step in planned if step.get("tool") in allowed_tools]

    planned = plan_task(objective)
    return [step for step in planned if step.get("tool") in allowed_tools]


def _record_tool_invocation(
    db_session,
    execution_id: UUID,
    tool_name: str,
    status: str,
    duration_ms: float,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
) -> None:
    invocation = ToolInvocation(
        execution_task_id=None,
        agent_execution_id=execution_id,
        tool_name=tool_name,
        status=status,
        duration_ms=duration_ms,
        input=tool_input,
        output=tool_output,
    )
    db_session.add(invocation)
    db_session.commit()


def _persist_artifact(
    db_session,
    execution: AgentExecution,
    artifact_type: str,
    uri: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    artifact = ExecutionArtifact(
        session_id=execution.session_id,
        agent_execution_id=execution.id,
        task_id=None,
        artifact_type=artifact_type,
        uri=uri,
        metadata=metadata or {},
    )
    db_session.add(artifact)
    db_session.commit()


def run_agent_execution(
    db_session,
    agent: Agent,
    execution: AgentExecution,
    allowed_tools: set[str],
) -> dict[str, Any]:
    runtime_state = execution.runtime_state or {}
    sandbox_id = runtime_state.get("sandbox_id")
    sandbox_session = None
    if sandbox_id:
        try:
            sandbox_session = sandbox_service.get_sandbox_session(db_session, UUID(sandbox_id))
        except Exception:
            sandbox_session = None

    if sandbox_session is None:
        workspace_id = None
        if isinstance(execution.input, dict):
            workspace_id = execution.input.get("workspace_id")

        sandbox_session = sandbox_service.create_sandbox_session(
            db_session,
            {
                "workspace_id": workspace_id,
                "project_id": execution.project_id,
                "agent_execution_id": execution.id,
                "policy": agent.execution_policy,
                "runtime_settings": agent.runtime_settings,
            },
        )
        execution.runtime_state = {**runtime_state, "sandbox_id": str(sandbox_session.id)}
        db_session.commit()

    policy = _default_policy(agent)

    state: dict[str, Any] = {
        "objective": execution.objective,
        "agent_id": str(agent.id),
        "execution_id": str(execution.id),
        "allowed_tools": allowed_tools,
        "plan": [],
        "results": [],
        "errors": [],
        "retries": 0,
        "policy": policy,
    }

    def plan_node(data: dict[str, Any]) -> dict[str, Any]:
        plan = _build_plan(agent, data["objective"], allowed_tools)
        data["plan"] = plan[: policy["max_steps"]]
        publish_agent_event(
            db_session,
            execution.id,
            "plan_created",
            {"steps": [step.get("tool") for step in data["plan"]]},
        )
        return data

    def execute_node(data: dict[str, Any]) -> dict[str, Any]:
        for idx, step in enumerate(data["plan"]):
            step_tool = step.get("tool")
            step_input = step.get("input", {})

            if step_tool == "delegate":
                agent_type = str(step_input.get("agent_type", ""))
                objective = str(step_input.get("objective", execution.objective))
                workers = [
                    candidate
                    for candidate in agent_service.list_agents(db_session)
                    if candidate.agent_type == agent_type
                ]
                if not workers:
                    data["errors"].append({"step": "delegate", "error": f"No agent for type {agent_type}"})
                    continue

                child = agent_service.create_execution(
                    db_session,
                    workers[0].id,
                    objective,
                    execution.project_id,
                    execution.session_id,
                    {},
                    parent_execution_id=execution.id,
                )
                get_agent_queue().enqueue(
                    "app.workers.agent_worker.process_agent_execution",
                    str(child.id),
                    job_timeout=900,
                )
                publish_agent_event(
                    db_session,
                    execution.id,
                    "delegate_dispatched",
                    {"agent_id": str(workers[0].id), "execution_id": str(child.id)},
                )
                data["results"].append(
                    {
                        "tool": "delegate",
                        "input": step_input,
                        "output": {"execution_id": str(child.id)},
                        "status": "completed",
                        "attempts": 1,
                        "duration_ms": 0,
                    }
                )
                continue

            if step_tool not in allowed_tools:
                data["errors"].append({"step": step_tool, "error": "Tool not permitted"})
                continue

            publish_agent_event(
                db_session,
                execution.id,
                "tool_started",
                {"tool": step_tool, "index": idx + 1},
            )

            attempts = 0
            max_retries = policy["max_retries"]
            last_error = None
            while attempts <= max_retries:
                db_session.refresh(execution)
                if execution.status == "canceled":
                    data["errors"].append({"step": step_tool, "error": "Execution canceled"})
                    return data

                attempts += 1
                start = time.time()
                try:
                    tool_exec = sandbox_service.create_tool_execution(
                        db_session,
                        sandbox_session,
                        {
                            "tool_name": step_tool,
                            "input": step_input,
                            "timeout_seconds": agent.runtime_settings.get("timeout_seconds"),
                        },
                    )
                    duration_ms = tool_exec.duration_ms or (time.time() - start) * 1000
                    output = tool_exec.output
                    metrics_collector.record_tool_execution(
                        step_tool,
                        int(duration_ms),
                        success=tool_exec.status == "completed",
                        attempts=attempts,
                    )
                    _record_tool_invocation(
                        db_session,
                        execution.id,
                        step_tool,
                        tool_exec.status,
                        duration_ms,
                        step_input,
                        output,
                    )
                    publish_agent_event(
                        db_session,
                        execution.id,
                        "tool_completed",
                        {"tool": step_tool, "duration_ms": duration_ms, "attempts": attempts},
                    )
                    data["results"].append(
                        {
                            "tool": step_tool,
                            "input": step_input,
                            "output": output,
                            "status": "completed",
                            "attempts": attempts,
                            "duration_ms": duration_ms,
                        }
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    duration_ms = (time.time() - start) * 1000
                    last_error = str(exc)
                    metrics_collector.record_tool_execution(step_tool, int(duration_ms), success=False, attempts=attempts)
                    publish_agent_event(
                        db_session,
                        execution.id,
                        "tool_failed",
                        {"tool": step_tool, "error": last_error, "attempts": attempts},
                    )
                    if attempts > max_retries:
                        _record_tool_invocation(
                            db_session,
                            execution.id,
                            step_tool,
                            "failed",
                            duration_ms,
                            step_input,
                            {"error": last_error},
                        )
                        data["errors"].append({"step": step_tool, "error": last_error})
                    else:
                        data["retries"] += 1
                        continue

        return data

    graph = StateGraph(dict)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", END)
    graph.set_entry_point("plan")

    publish_agent_event(
        db_session,
        execution.id,
        "execution_started",
        {"objective": execution.objective, "agent": agent.name},
    )

    overall_start = time.time()
    execution.started_at = _utc_now()
    execution.status = "running"
    db_session.commit()

    result_state = graph.compile().invoke(state)

    runtime_report = {
        "objective": execution.objective,
        "results": result_state["results"],
        "errors": result_state["errors"],
        "retries": result_state["retries"],
    }

    execution.plan = {"steps": result_state["plan"]}
    execution.output = runtime_report
    execution.runtime_state = {"last_state": "completed"}
    execution.metrics = {
        "steps_total": len(result_state["plan"]),
        "steps_completed": len([r for r in result_state["results"] if r.get("status") == "completed"]),
        "steps_failed": len(result_state["errors"]),
        "total_retries": result_state["retries"],
        "duration_ms": int((time.time() - overall_start) * 1000),
    }
    execution.retry_count = result_state["retries"]
    execution.completed_at = _utc_now()
    execution.status = "failed" if result_state["errors"] else "completed"
    if result_state["errors"]:
        execution.error = str(result_state["errors"][0])
    db_session.commit()

    _persist_artifact(
        db_session,
        execution,
        "agent_report",
        f"inline://agent-executions/{execution.id}/report",
        {"report": runtime_report},
    )

    publish_agent_event(
        db_session,
        execution.id,
        "execution_completed" if execution.status == "completed" else "execution_failed",
        {"status": execution.status, "errors": result_state["errors"]},
    )

    if agent.memory_config.get("enable_runtime", True):
        agent_service.create_memory(
            db_session,
            agent.id,
            {
                "project_id": execution.project_id,
                "execution_id": execution.id,
                "scope": "runtime",
                "key": "last_execution",
                "payload": runtime_report,
                "summary": execution.objective,
            },
        )

    if agent.memory_config.get("enable_project", False) and execution.project_id:
        agent_service.create_memory(
            db_session,
            agent.id,
            {
                "project_id": execution.project_id,
                "execution_id": execution.id,
                "scope": "project",
                "key": "project_snapshot",
                "payload": {"objective": execution.objective, "output": runtime_report},
                "summary": "Project memory snapshot",
            },
        )

    if agent.runtime_settings.get("cleanup_on_complete", True):
        sandbox_service.stop_sandbox_session(db_session, sandbox_session)

    return runtime_report

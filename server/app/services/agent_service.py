from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_execution import AgentExecution
from app.models.agent_memory import AgentMemory
from app.models.tool_permission import ToolPermission
from app.tools.registry import TOOLS


DEFAULT_AGENT_TYPES: dict[str, dict[str, Any]] = {
    "diagnostic": {
        "instructions": "Diagnose runtime failures with structured tool usage and clear remediation steps.",
        "execution_policy": {"max_retries": 2, "max_steps": 6},
    },
    "api_testing": {
        "instructions": "Execute API testing workflows; focus on latency, failures, and coverage gaps.",
        "execution_policy": {"max_retries": 1, "max_steps": 4},
    },
    "browser_automation": {
        "instructions": "Automate browser workflows with deterministic steps and artifact capture.",
        "execution_policy": {"max_retries": 1, "max_steps": 5},
    },
    "deployment_investigation": {
        "instructions": "Investigate deployment regressions with telemetry and log correlation.",
        "execution_policy": {"max_retries": 2, "max_steps": 6},
    },
    "coordinator": {
        "instructions": "Coordinate specialized agents and merge their findings into a single report.",
        "execution_policy": {"max_retries": 0, "max_steps": 4, "allow_delegate": True},
    },
}

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "name": "Diagnostic Agent",
        "agent_type": "diagnostic",
        "description": "Focused on runtime diagnostics and failure analysis.",
        "tools": ["log_analysis", "api_test"],
    },
    {
        "name": "API Testing Agent",
        "agent_type": "api_testing",
        "description": "Executes API probes and reports regressions.",
        "tools": ["api_test"],
    },
    {
        "name": "Browser Automation Agent",
        "agent_type": "browser_automation",
        "description": "Automates browser flows and captures artifacts.",
        "tools": ["api_test"],
    },
    {
        "name": "Deployment Investigation Agent",
        "agent_type": "deployment_investigation",
        "description": "Correlates deployment telemetry and remediation steps.",
        "tools": ["log_analysis", "api_test"],
    },
]


def ensure_default_agents(db: Session) -> list[Agent]:
    created: list[Agent] = []
    for spec in DEFAULT_AGENTS:
        existing = db.query(Agent).filter(Agent.name == spec["name"]).first()
        if existing:
            continue

        payload = {
            "name": spec["name"],
            "description": spec["description"],
            "agent_type": spec["agent_type"],
        }
        agent = create_agent(db, payload)
        allowed = [tool for tool in spec.get("tools", []) if tool in TOOLS]
        permissions = [{"tool_name": tool, "allowed": True, "config": {}} for tool in allowed]
        if permissions:
            replace_permissions(db, agent.id, permissions)
        created.append(agent)

    return created


def list_agents(db: Session) -> list[Agent]:
    return db.query(Agent).order_by(Agent.updated_at.desc()).all()


def get_agent(db: Session, agent_id: UUID) -> Agent | None:
    return db.get(Agent, agent_id)


def create_agent(db: Session, payload: dict[str, Any]) -> Agent:
    agent_type = payload.get("agent_type", "diagnostic")
    defaults = DEFAULT_AGENT_TYPES.get(agent_type, {})
    agent = Agent(
        name=payload.get("name"),
        description=payload.get("description", ""),
        agent_type=agent_type,
        instructions=payload.get("instructions", defaults.get("instructions", "")),
        execution_policy=payload.get("execution_policy", defaults.get("execution_policy", {})),
        runtime_settings=payload.get("runtime_settings", {}),
        memory_config=payload.get("memory_config", {"enable_runtime": True}),
        status=payload.get("status", "active"),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def update_agent(db: Session, agent: Agent, payload: dict[str, Any]) -> Agent:
    for key, value in payload.items():
        if value is None:
            continue
        if hasattr(agent, key):
            setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent: Agent) -> None:
    db.delete(agent)
    db.commit()


def list_permissions(db: Session, agent_id: UUID) -> list[ToolPermission]:
    return (
        db.query(ToolPermission)
        .filter(ToolPermission.agent_id == agent_id)
        .order_by(ToolPermission.tool_name.asc())
        .all()
    )


def replace_permissions(db: Session, agent_id: UUID, permissions: list[dict[str, Any]]) -> list[ToolPermission]:
    db.query(ToolPermission).filter(ToolPermission.agent_id == agent_id).delete()
    created: list[ToolPermission] = []
    for permission in permissions:
        entry = ToolPermission(
            agent_id=agent_id,
            tool_name=permission.get("tool_name"),
            allowed=permission.get("allowed", True),
            config=permission.get("config", {}),
        )
        db.add(entry)
        created.append(entry)
    db.commit()
    for entry in created:
        db.refresh(entry)
    return created


def get_allowed_tools(db: Session, agent_id: UUID) -> set[str]:
    permissions = list_permissions(db, agent_id)
    if not permissions:
        return set()
    return {permission.tool_name for permission in permissions if permission.allowed}


def create_execution(
    db: Session,
    agent_id: UUID,
    objective: str,
    project_id: UUID | None,
    session_id: UUID | None,
    input_payload: dict[str, Any],
    parent_execution_id: UUID | None = None,
) -> AgentExecution:
    execution = AgentExecution(
        agent_id=agent_id,
        project_id=project_id,
        session_id=session_id,
        parent_execution_id=parent_execution_id,
        objective=objective,
        status="queued",
        input=input_payload,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def list_executions(db: Session, agent_id: UUID) -> list[AgentExecution]:
    return (
        db.query(AgentExecution)
        .filter(AgentExecution.agent_id == agent_id)
        .order_by(AgentExecution.created_at.desc())
        .all()
    )


def get_execution(db: Session, execution_id: UUID) -> AgentExecution | None:
    return db.get(AgentExecution, execution_id)


def update_execution(db: Session, execution: AgentExecution, payload: dict[str, Any]) -> AgentExecution:
    for key, value in payload.items():
        if value is None:
            continue
        if hasattr(execution, key):
            setattr(execution, key, value)
    db.commit()
    db.refresh(execution)
    return execution


def create_memory(db: Session, agent_id: UUID, payload: dict[str, Any]) -> AgentMemory:
    memory = AgentMemory(
        agent_id=agent_id,
        project_id=payload.get("project_id"),
        execution_id=payload.get("execution_id"),
        scope=payload.get("scope", "runtime"),
        key=payload.get("key"),
        payload=payload.get("payload", {}),
        summary=payload.get("summary", ""),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def list_memory(
    db: Session,
    agent_id: UUID,
    project_id: UUID | None = None,
    scope: str | None = None,
) -> list[AgentMemory]:
    query = db.query(AgentMemory).filter(AgentMemory.agent_id == agent_id)
    if project_id is not None:
        query = query.filter(AgentMemory.project_id == project_id)
    if scope is not None:
        query = query.filter(AgentMemory.scope == scope)
    return query.order_by(AgentMemory.updated_at.desc()).all()

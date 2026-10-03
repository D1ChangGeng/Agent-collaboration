"""Descriptive organization vocabulary over existing authenticated bindings."""
from __future__ import annotations

from copy import deepcopy

ORGANIZATION_MODEL = {
    "schema_version": "acs-agent-organization/1",
    "task_agent_status": "proposed_terminology",
    "levels": {"root": "project responsibility", "route": "development-line responsibility",
               "task": "explicit task responsibility"},
    "responsibility_roles": ["project_coordination", "route_coordination", "engineer",
                             "reviewer", "specialist", "finalizer"],
    "authorization": "Grant, Policy, Profile, budget and live boundary checks",
    "binding_model": "Existing Scope, AgentSlot, WorkItem and Session bindings; Task Agent is a descriptive projection",
}


def organization_model() -> dict:
    return deepcopy(ORGANIZATION_MODEL)


def organization_projection(primary_role: str | None, *, level: str | None = None,
                            responsibilities: list[str] | None = None) -> dict:
    inferred = ("root" if primary_role == "root" else "route" if primary_role == "route"
             else "task" if primary_role in {"engineer", "reviewer", "specialist", "finalizer"} else "unknown")
    default_roles = (["project_coordination"] if primary_role == "root" else ["route_coordination"]
                     if primary_role == "route" else [primary_role] if inferred == "task" else [])
    selected_level = level or inferred
    duties = list(responsibilities) if responsibilities else default_roles
    return {"level": selected_level, "level_source": "explicit_declaration" if level else "legacy_projection", "label": {"root": "Root Agent", "route": "Route Agent",
            "task": "Task Agent", "unknown": "Unclassified Agent"}[selected_level],
            "primary_role": primary_role, "responsibilities": duties,
            "terminology_status": "proposed" if selected_level == "task" else "existing",
            "permission_effect": "descriptive_only"}

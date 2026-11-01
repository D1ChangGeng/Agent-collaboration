"""Descriptive organization vocabulary over existing authenticated bindings."""
from __future__ import annotations

from copy import deepcopy

ORGANIZATION_MODEL = {
    "schema_version": "acs-agent-organization/2",
    "management_levels": ["client", "root", "route"],
    "levels": {"client": "trusted Client management", "root": "project responsibility", "route": "route management",
               "agent": "ordinary collaborator; no management tier"},
    "responsibility_roles": ["project_coordination", "route_coordination", "engineer",
                             "reviewer", "specialist", "finalizer"],
    "authorization": "trusted caller binding, scoped Grants and live boundary checks",
    "binding_model": "Project, Scope, stable AgentSlot, trusted Client and real Native Session bindings",
}


def organization_model() -> dict:
    return deepcopy(ORGANIZATION_MODEL)


def management_tool_allowed(name: str, profile: str, *, trusted_client: bool) -> bool:
    """One eligibility rule for discovery and calls; scoped checks still apply."""
    if name in {"configure_root", "configure_project"}:
        return trusted_client or profile in {"root_manager", "operator"}
    if name == "create_route":
        return trusted_client or profile == "root_manager"
    if name in {"configure_team", "update_route"}:
        return trusted_client or profile in {"root_manager", "route_manager"}
    return True


def organization_projection(primary_role: str | None, *, level: str | None = None,
                            responsibilities: list[str] | None = None) -> dict:
    inferred = ("client" if primary_role == "client" else "root" if primary_role == "root" else "route" if primary_role == "route"
             else "agent" if primary_role in {"engineer", "reviewer", "specialist", "finalizer"} else "unknown")
    default_roles = (["project_coordination"] if primary_role == "root" else ["route_coordination"]
                     if primary_role == "route" else [primary_role] if inferred == "agent" else [])
    selected_level = ("agent" if level == "task" else level) or inferred
    duties = list(responsibilities) if responsibilities else default_roles
    return {"level": selected_level, "level_source": "explicit_declaration" if level else "binding_projection", "label": {"client": "Trusted Client", "root": "Root Agent", "route": "Route Manager",
            "agent": "Collaborator", "unknown": "Unclassified Agent"}[selected_level],
            "primary_role": primary_role, "responsibilities": duties,
            "terminology_status": "current",
            "permission_effect": "descriptive_only"}

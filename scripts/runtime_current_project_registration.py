"""Register owner project identity and current management file locations."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from runtime_project_adoption import validate
from workspace_setup import _exact_root, _safe_path

from runtime.models import CommandEnvelope
from runtime.project_common import digest, handle
from runtime.project_service import ProjectService
from runtime.surface_config import configured_service


def preview(root, specification, settings, catalog):
    root = _exact_root(Path(root), "Management Root")
    identity = validate(root)
    required = {"schema_version", "scope_id", "agent_slot_id", "name", "route_goals"}
    allowed = required | {"source_root", "expected_commit", "expected_tree", "source_id", "repository_identity", "skill_catalog_path", "max_source_bytes"}
    if not isinstance(specification, dict) or not required <= set(specification) or set(specification) - allowed:
        raise ValueError("invalid current-file project registration")
    if specification["schema_version"] != "acs-runtime-registration/1":
        raise ValueError("unknown registration specification")
    registry = json.loads((root / ".agents/coordination/routes.yaml").read_text())
    goals = specification["route_goals"]
    if not isinstance(goals, dict) or set(goals) != {route["id"] for route in registry["routes"]}:
        raise ValueError("supply the goal of each registered Route")
    inventory = {}
    def entry(relative, optional=False):
        selected = _safe_path(root, relative)
        if selected is None or not selected.is_file():
            if optional:
                return None
            raise ValueError("management document is unavailable: " + relative)
        inventory[relative] = digest(selected.read_bytes().hex())
        return relative
    instructions = [entry("AGENTS.md"), entry(".agents/coordination/ROOT-BASELINE.md")]
    for relative in (".agents/coordination/PROJECT.md", "../AGENTS.md"):
        if relative.startswith("../"):
            continue
        selected = entry(relative, True)
        if selected:
            instructions.append(selected)
    index = entry(".agents/knowledge/index.yaml", True)
    def context(paths, indexes):
        return {"management": {"mode": "current_files", "machine_id": "local", "path": str(root)},
                "instruction_paths": paths, "knowledge_index_paths": indexes,
                "management_identity": {"project_id": identity["project_id"], "root_id": identity["root_id"]}}
    routes = []
    for route in registry["routes"]:
        route_path = route["path"]
        entry(route_path + "/.agents/route.yaml")
        route_index = entry(route_path + "/.agents/knowledge/index.yaml", True)
        route_context = context(instructions + [entry(route_path + "/AGENTS.md")], [route_index] if route_index else [])
        route_context["route_path"] = route_path
        suffix = digest([settings.context.tenant_id, identity["project_id"], route["id"]])
        routes.append({**route, "scope_id": "scope-" + suffix, "goal": goals[route["id"]], "context_manifest": route_context})
    value = {"schema_version": "acs-runtime-registration-plan/1", "mode": "current_files",
             "project_id": identity["project_id"], "root_id": identity["root_id"],
             "management_root": str(root), "specification": specification, "routes": routes,
             "root_context": context(instructions, [index] if index else []), "inventory": inventory,
             "configuration_digest": digest(settings.model_dump(mode="json")), "catalog_digest": digest(catalog)}
    return {**value, "plan_digest": digest(value), "state": "planned", "domain_state": "not_read"}


def apply(plan, config_path, catalog, *, adopt_schema=False):
    specification = plan["specification"]
    with configured_service(config_path) as (shared, settings):
        credential = settings.credential()
        shared.authenticate(credential)
        projects = ProjectService(shared, catalog, profile="root_manager")
        if adopt_schema:
            projects.initialize()
        context = shared.authority.context
        now = datetime.now(UTC)
        def command(kind, stage, revision=0):
            request = "registration-" + digest([plan["plan_digest"], stage])
            return CommandEnvelope(command_id=request, command_type=kind, idempotency_key=request,
                correlation_id=request, tenant_id=context.tenant_id, authority_id=context.authority_id,
                authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
                grant_ref=context.grant_ref, target_kind="project", target_id=plan["project_id"],
                expected_revision=revision, issued_at=now, deadline=None)
        with shared.authority._connect() as connection:
            existing = connection.execute("SELECT root_id,scope_id,name,context_manifest,revision FROM collaboration_projects "
                "WHERE tenant_id=%s AND project_id=%s", (context.tenant_id, plan["project_id"])).fetchone()
        if existing is None:
            projects.admit_project(command("project.adopt", "project"), project_id=plan["project_id"],
                root_id=plan["root_id"], scope_id=specification["scope_id"], agent_slot_id=specification["agent_slot_id"],
                name=specification["name"], context_manifest=plan["root_context"], credential=credential)
        else:
            if existing[:2] != (plan["root_id"], specification["scope_id"]):
                raise ValueError("existing Project identity differs")
            if existing[3] != plan["root_context"]:
                projects.execute("configure_project", {"project_id": plan["project_id"],
                    "client_request_id": "context-" + plan["plan_digest"], "expected_revision": existing[4],
                    "changes": plan["root_context"]}, credential)
        for route in plan["routes"]:
            with shared.authority._connect() as connection:
                current = connection.execute("SELECT revision,definition,state FROM collaboration_routes WHERE tenant_id=%s "
                    "AND project_id=%s AND route_id=%s", (context.tenant_id, plan["project_id"], route["id"])).fetchone()
                project_revision = connection.execute("SELECT revision FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s",
                    (context.tenant_id, plan["project_id"])).fetchone()[0]
            if current is None:
                projects.execute("create_route", {"project_id": plan["project_id"], "client_request_id": "route-" + digest([plan["plan_digest"],route["id"]]),
                    "root_handle": handle("project",plan["project_id"],plan["root_id"]), "route_id": route["id"],
                    "expected_root_revision": project_revision, "display_name": route["display_name"], "goal": route["goal"]}, credential)
                current = (1, {}, "active")
            if current[1].get("context_manifest") != route["context_manifest"] or current[2] != route["status"]:
                projects.execute("update_route", {"project_id":plan["project_id"], "client_request_id":"route-context-"+digest([plan["plan_digest"],route["id"]]),
                    "route_handle":handle("route",plan["project_id"],route["id"]), "expected_revision":current[0],
                    "changes":{"context_manifest":route["context_manifest"],"state":route["status"]}, "reason":"current management documents"}, credential)
        observed, _pack, _ = projects.execute("load_project", {"project_id":plan["project_id"]}, credential)
        return {"schema_version":"acs-runtime-registration-receipt/1", "project_id":plan["project_id"],
                "root_id":plan["root_id"], "state":"registered", "context_state":observed,
                "management_root":str(plan["management_root"]), "source_selection":"agent_explicit",
                "tracked_management_files_changed":False, "routes":plan["routes"]}

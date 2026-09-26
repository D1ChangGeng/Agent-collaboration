"""Explicit installer bridge from preserved Git metadata to the Runtime Domain.

Preview reads only. Apply exports an authorized clean Source and commits Domain
registration; it never enrolls credentials, rewrites management files or starts
execution. Immutable CAS objects survive an aborted transaction for inspection.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime_project_adoption import validate
from workspace_setup import _exact_root, _safe_path

# The setup Skill may use an installed Runtime package, or the exact adjacent
# checkout when developing both. It remains an optional installer dependency.
_CHECKOUT = Path(__file__).resolve().parents[1]
if (_CHECKOUT / "runtime").is_dir() and str(_CHECKOUT) not in sys.path:
    sys.path.insert(0, str(_CHECKOUT))

from runtime.models import CommandEnvelope
from runtime.project_common import IDENTIFIER, digest, handle
from runtime.project_service import ProjectService
from runtime.project_source import ProjectSources
from runtime.source_models import SourceRequest
from runtime.surface_config import configured_service, load_settings
from runtime.surfaces import SharedService


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise ValueError("Source Git observation failed")
    return result.stdout.decode("utf-8").strip()


def preview(root, specification, settings, catalog):
    required = {"schema_version", "source_root", "expected_commit", "expected_tree", "scope_id", "agent_slot_id",
                "name", "source_id", "repository_identity", "route_goals"}
    if (not isinstance(specification, dict) or not required <= set(specification)
            or set(specification) - required - {"skill_catalog_path", "max_source_bytes"}
            or specification["schema_version"] != "acs-runtime-registration/1"):
        raise ValueError("invalid Runtime registration specification")
    root = _exact_root(Path(root), "Management Root")
    identity = validate(root)
    source = _exact_root(Path(specification["source_root"]), "Source checkout")
    if (not root.is_relative_to(source) or Path(_git(source, "rev-parse", "--show-toplevel")) != source
            or _git(source, "rev-parse", "HEAD") != specification["expected_commit"]
            or _git(source, "rev-parse", "HEAD^{tree}") != specification["expected_tree"]
            or _git(source, "status", "--porcelain=v1", "--untracked-files=all")):
        raise ValueError("registration requires the exact clean containing Source checkout")
    for key in ("scope_id", "agent_slot_id", "source_id"):
        if not isinstance(specification[key], str) or not IDENTIFIER.fullmatch(specification[key]):
            raise ValueError("invalid registration identity")
    if (not isinstance(specification["name"], str) or not 1 <= len(specification["name"]) <= 256
            or not isinstance(specification["repository_identity"], dict)):
        raise ValueError("invalid registration metadata")
    maximum = specification.get("max_source_bytes", 16*1024*1024)
    if type(maximum) is not int or not 1 <= maximum <= 256*1024*1024:
        raise ValueError("invalid Source export bound")
    registry = json.loads((root / ".agents/coordination/routes.yaml").read_bytes())
    if len(registry["routes"]) > 32:
        raise ValueError("registration exceeds the bounded Route export count")
    goals = specification["route_goals"]
    if (not isinstance(goals, dict) or set(goals) != {r["id"] for r in registry["routes"]}
            or any(not isinstance(goal, str) or not 1 <= len(goal) <= 8192 for goal in goals.values())):
        raise ValueError("registration requires an explicit goal for each existing Route")
    inventory = {}
    def path(relative_root, relative, *, optional=False):
        target = _safe_path(relative_root, relative)
        if target is None:
            raise ValueError("registration context path is unsafe")
        if not target.is_file():
            if optional and not target.exists():
                return None
            raise ValueError("registration context path is unavailable")
        logical = target.relative_to(source).as_posix()
        if not _git(source, "ls-files", "--", logical):
            raise ValueError("registration context must be tracked in Source")
        inventory[logical] = hashlib.sha256(target.read_bytes()).hexdigest()
        return logical
    root_instructions = [path(root, "AGENTS.md"), path(root, ".agents/coordination/ROOT-BASELINE.md")]
    path(root, ".agents/manifest.json")
    registry_path = path(root, ".agents/coordination/routes.yaml")
    root_index = path(root, ".agents/knowledge/index.yaml", optional=True)
    skill_path = path(source, specification["skill_catalog_path"]) if specification.get("skill_catalog_path") else None
    management_path = root.relative_to(source).as_posix()
    def context(source_id, instructions, indexes):
        return {"management": {"source_id": source_id, "path": management_path},
                "instruction_paths": instructions, "knowledge_index_paths": indexes,
                **({"skill_catalog": {"source_id": source_id, "path": skill_path}} if skill_path else {})}
    routes = []
    for route in sorted(registry["routes"], key=lambda item: item["id"]):
        directory = _safe_path(root, route["path"])
        if directory is None or not directory.is_dir():
            raise ValueError("registered Route path is unavailable")
        path(directory, ".agents/route.yaml")
        instructions = root_instructions + [path(directory, "AGENTS.md")]
        index = path(directory, ".agents/knowledge/index.yaml", optional=True)
        suffix = digest([settings.context.tenant_id, identity["project_id"], route["id"]])
        source_id = "route-source-" + suffix
        route_context = context(source_id, instructions, [index] if index else [])
        route_context["route_path"] = directory.relative_to(source).as_posix()
        routes.append({**route, "scope_id": "scope-" + suffix, "source_id": source_id,
            "goal": goals[route["id"]], "source_path": directory.relative_to(source).as_posix(),
            "context_manifest": route_context})
    providers = {config.scope_id: config for config in settings.artifact_configs()}
    cas_roots = []
    for provider in providers.values():
        cas = _exact_root(Path(provider.root), "CAS root")
        if any(cas == other or cas.is_relative_to(other) or other.is_relative_to(cas) for other in cas_roots):
            raise ValueError("CAS Scope roots must be disjoint")
        cas_roots.append(cas)
    for scope in (specification["scope_id"], *(route["scope_id"] for route in routes)):
        provider = providers.get(scope)
        if provider is None or not any(source == Path(p) or source.is_relative_to(Path(p)) for p in provider.authorized_source_roots):
            raise ValueError("every planned Scope needs an explicitly configured Source/CAS provider")
    plan = {"schema_version": "acs-runtime-registration-plan/1", "project_id": identity["project_id"],
        "root_id": identity["root_id"], "management_root": str(root), "source_root": str(source),
        "specification": specification, "registry_path": registry_path, "routes": routes,
        "root_context": context(specification["source_id"], root_instructions, [root_index] if root_index else []),
        "inventory": inventory, "configuration_digest": digest(settings.model_dump(mode="json")),
        "catalog_digest": digest(catalog)}
    return {**plan, "plan_digest": digest(plan), "state": "planned", "domain_state": "not_read"}


def apply(root, specification, config_path, catalog, expected_plan_digest, *, adopt_schema=False):
    settings = load_settings(config_path)
    plan = preview(root, specification, settings, catalog)
    if plan["plan_digest"] != expected_plan_digest:
        raise ValueError("registration preview changed; obtain and review a new plan")
    with configured_service(config_path, expected_settings=settings) as (shared, actual), ExitStack() as resources:
        credential = actual.credential()
        shared.authenticate(credential)
        providers = actual.artifact_configs()
        roots = (providers[0].authorized_source_roots if len(providers) == 1 else
                 {item.scope_id: item.authorized_source_roots for item in providers if item.authorized_source_roots})
        sources = ProjectSources(shared.authority._artifact_store, roots)
        resources.callback(sources.close)
        now = datetime.now(UTC)
        def command(kind, stage, revision=0):
            identity = "registration-" + digest([plan["plan_digest"], stage])
            context = shared.authority.context
            return CommandEnvelope(command_id=identity, command_type=kind, idempotency_key=identity,
                correlation_id=identity, tenant_id=context.tenant_id, authority_id=context.authority_id,
                authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
                grant_ref=context.grant_ref, target_kind="project", target_id=plan["project_id"],
                expected_revision=revision, issued_at=now, deadline=now+timedelta(minutes=5))
        with shared.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            authority._authorize(command("project.adopt", "authorize"), cursor, "project.adopt", specification["scope_id"])
            # The outer transaction controls schema, identity, Source and Route
            # composition. CAS bytes are immutable authorized export, not a
            # substitute for the final committed Domain registration.
            projects = ProjectService(SharedService(authority, shared.authenticator), catalog,
                                      profile="root_manager", sources=sources)
            if adopt_schema:
                projects.initialize()
            cursor.execute("SELECT root_id,scope_id,name,context_manifest FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s FOR UPDATE",
                           (authority.context.tenant_id, plan["project_id"]))
            existing = cursor.fetchone()
            if existing is None:
                projects.admit_project(command("project.adopt", "adopt"), project_id=plan["project_id"], root_id=plan["root_id"],
                    scope_id=specification["scope_id"], agent_slot_id=specification["agent_slot_id"], name=specification["name"],
                    context_manifest=plan["root_context"], credential=credential)
            elif existing != (plan["root_id"], specification["scope_id"], specification["name"], plan["root_context"]):
                raise ValueError("existing Runtime project needs an explicit metadata migration")
            def source(source_id, scope, route_id):
                cursor.execute("SELECT revision,current_commit,repository_identity FROM collaboration_sources "
                               "WHERE tenant_id=%s AND project_id=%s AND source_id=%s FOR UPDATE",
                               (authority.context.tenant_id, plan["project_id"], source_id))
                old = cursor.fetchone()
                if old and old[1:] == (specification["expected_commit"], specification["repository_identity"]):
                    _, snapshot = projects._snapshot(cursor, {"project_id": plan["project_id"], "source_id": source_id})
                    if (snapshot.scope_id, snapshot.root_id, snapshot.route_id, snapshot.repository_root,
                            snapshot.source_tree) != (scope, plan["root_id"], route_id, plan["source_root"], specification["expected_tree"]):
                        raise ValueError("existing Source binding identity differs from the registration plan")
                    return
                request = SourceRequest(root=plan["source_root"], tenant_id=authority.context.tenant_id, scope_id=scope,
                    root_id=plan["root_id"], route_id=route_id, expected_commit=specification["expected_commit"],
                    expected_tree=specification["expected_tree"], include_untracked=False,
                    max_bytes=specification.get("max_source_bytes", 16*1024*1024))
                projects.admit_source(command("source.bind", source_id, old[0] if old else 0), project_id=plan["project_id"],
                    source_id=source_id, request=request, repository_identity=specification["repository_identity"], credential=credential)
            source(specification["source_id"], specification["scope_id"], None)
            for route in plan["routes"]:
                cursor.execute("SELECT scope_id,revision,definition,state FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s AND route_id=%s FOR UPDATE",
                               (authority.context.tenant_id, plan["project_id"], route["id"]))
                current = cursor.fetchone()
                created = current is None
                if current is None:
                    cursor.execute("SELECT revision FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s",
                                   (authority.context.tenant_id, plan["project_id"]))
                    args = {"project_id": plan["project_id"], "root_handle": handle("project", plan["project_id"], plan["root_id"]),
                        "client_request_id": "register-route-"+digest([plan["plan_digest"], route["id"]]),
                        "expected_root_revision": cursor.fetchone()[0], "route_id": route["id"], "display_name": route["display_name"],
                        "goal": route["goal"], "source_binding_ids": [], "deadline": (now+timedelta(minutes=5)).isoformat()}
                    projects.execute("create_route", args, credential)
                    current = (route["scope_id"], 1, {}, "active")
                if current[0] != route["scope_id"]:
                    raise ValueError("existing Route Scope requires explicit migration")
                if not created and (current[2].get("goal"), current[2].get("display_name"), current[3]) != (
                        route["goal"], route["display_name"], route["status"]):
                    raise ValueError("existing Runtime Route metadata requires explicit reconciliation")
                source(route["source_id"], route["scope_id"], route["id"])
                if (current[2].get("context_manifest") != route["context_manifest"]
                        or current[2].get("management_source_readback", {}).get("source_commit") != specification["expected_commit"]):
                    projects.execute("update_route", {"project_id": plan["project_id"], "route_handle": handle("route", plan["project_id"], route["id"]),
                        "client_request_id": "register-context-"+digest([plan["plan_digest"], route["id"]]), "expected_revision": current[1],
                        "changes": {"context_manifest": route["context_manifest"], "state": route["status"]}, "reason": "explicit installer Source registration",
                        "deadline": (now+timedelta(minutes=5)).isoformat()}, credential)
            if preview(root, specification, actual, catalog)["plan_digest"] != expected_plan_digest:
                raise ValueError("Source changed during Runtime registration")
        # A separate connection observes the committed state. A successful
        # transaction alone is not reported as a complete context readback.
        readback = ProjectService(shared, catalog, profile="root_manager", sources=sources)
        state, pack, _ = readback.execute("load_project", {"project_id": plan["project_id"]}, credential)
        route_readbacks = []
        for route in plan["routes"]:
            route_handle = handle("route", plan["project_id"], route["id"])
            observed, route_pack, _ = readback.execute("load_project", {"project_id": plan["project_id"],
                "route_handle": route_handle, "context_view": "route_management"}, credential)
            route_readbacks.append({"route_handle": route_handle, "scope_id": route["scope_id"],
                "context_state": observed, "source_commit": route_pack.get("source_observation", {}).get("commit")})
        return {"schema_version": "acs-runtime-registration-receipt/1", "state": "registered",
            "project_id": plan["project_id"], "root_id": plan["root_id"], "plan_digest": plan["plan_digest"],
            "source_commit": specification["expected_commit"], "source_tree": specification["expected_tree"],
            "context_state": state, "project_revision": pack["project_revision"],
            "routes": route_readbacks,
            "tracked_management_files_changed": False, "execution_started": False, "evidence_class": "authority_source_readback"}

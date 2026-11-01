"""One Root configuration operation over the existing communication namespace.

Project IDs remain routing/authorization keys. This adds no separate Project
manager, workflow, task, schema migration or Client Slot.
"""
from __future__ import annotations

from copy import copy

from runtime.agent_organization import management_tool_allowed
from runtime.auth import LocalCredentialAuthenticator
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidToolArgument,
    NotFound,
    RevisionConflict,
)
from runtime.project_common import IDENTIFIER, canonical, digest, handle
from runtime.surfaces import SharedService


class RootManagement:
    def _configure_root_entry(self, args, credential):
        owner = self.service.authority.access_mode == "owner"
        if not owner or not management_tool_allowed("configure_root", self.profile, trusted_client=self.context.trusted_client):
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        project_id = args["project_id"]
        if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
            raise InvalidToolArgument("project_id", "Use a stable namespace identifier of 1–128 letters, digits, dots, underscores or hyphens, beginning with a letter or digit.")
        changes = dict(args["changes"])
        root_id = changes.pop("root_id", None)
        name = changes.pop("name", None)
        if root_id is not None and (not isinstance(root_id, str) or not IDENTIFIER.fullmatch(root_id)):
            raise InvalidToolArgument("changes.root_id", "Use a stable Root identifier, or omit it to reuse project_id at first setup.")
        if name is not None and (not isinstance(name, str) or not 1 <= len(name) <= 256):
            raise ValueError("Root name must contain one to 256 characters")
        manager = args.get("manager")
        if not changes and root_id is None and name is None and manager is None:
            raise InvalidToolArgument("changes", "Provide Root settings to change, or a manager to configure.")
        with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            command = self._command(authority, "project.configure_root", args)
            authority._authorize(command, cursor)
            # Covers concurrent first registration and updates of the same Root.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           ("root-config:" + self.context.tenant_id + ":" + project_id,))
            cursor.execute("SELECT scope_id,root_id,revision,context_manifest,name,state FROM collaboration_projects "
                           "WHERE tenant_id=%s AND project_id=%s FOR UPDATE",
                           (self.context.tenant_id, project_id))
            existing = cursor.fetchone()
            if existing is not None and existing[5] != "active":
                raise NotFound("root", project_id)
            created = existing is None
            if created:
                if not self.context.trusted_client:
                    raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
                if not name:
                    raise InvalidToolArgument("changes.name", "Give the new Root a readable name; no separate Project setup is required.")
                if args.get("expected_revision", 0) != 0:
                    raise RevisionConflict(project_id, args["expected_revision"], 0)
                selected_root = root_id or project_id
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                               ("root-identity:" + self.context.tenant_id + ":" + selected_root,))
                cursor.execute("SELECT project_id FROM collaboration_projects WHERE tenant_id=%s AND root_id=%s",
                               (self.context.tenant_id, selected_root))
                if cursor.fetchone() is not None:
                    raise InvalidToolArgument("changes.root_id", "Select the existing Root namespace or use a distinct Root identity.")
                manifest = self._management_manifest_changes({}, changes) if changes else {}
                scope = "scope-root-" + digest([self.context.tenant_id, project_id, selected_root])
                cursor.execute("INSERT INTO scopes VALUES (%s,%s,'{}','active')", (scope, self.context.tenant_id))
                registration = command.model_copy(update={"command_id": command.command_id + ":registration",
                    "idempotency_key": command.idempotency_key + ":registration", "command_type": "project.adopt",
                    "target_kind": "project", "target_id": project_id, "expected_revision": 0})
                registered = copy(self)
                registered.service = SharedService(authority, LocalCredentialAuthenticator(authority.context))
                registered.admit_project(registration, project_id=project_id, root_id=selected_root,
                    scope_id=scope, agent_slot_id=None, name=name, context_manifest=manifest, credential=credential)
                existing = (scope, selected_root, 1, manifest, name)
            bound, project, _ = self._authorize(authority, cursor, project_id, "configure_root", args)
            if manager is not None and not self.context.trusted_client and manager.get("agent_slot_id") != project[5]:
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            request_id = args.get("client_request_id")
            input_digest = digest(["configure_root", args])
            authority._lock_command_identity(cursor, command)
            prior = None
            if request_id:
                cursor.execute("SELECT input_digest,result_json FROM collaboration_commands WHERE tenant_id=%s "
                               "AND project_id=%s AND principal_ref=%s AND client_request_id=%s FOR UPDATE",
                               (self.context.tenant_id, project_id, self.context.principal_ref, request_id))
                prior = cursor.fetchone()
                if prior and prior[0] != input_digest:
                    raise IdempotencyConflict(request_id)
            if prior:
                return tuple(prior[1])
            previous = {"name": existing[4], "root_id": existing[1], **existing[3]}
            expected = args.get("if_unchanged", {})
            if not isinstance(expected, dict) or any(previous.get(key) != value for key, value in expected.items()):
                raise RevisionConflict(project_id, existing[2], existing[2], "if_unchanged",
                    "A Root property changed. Read the current Root context and reconsider the requested change; do not replace its old-value condition automatically.")
            if root_id is not None and root_id != existing[1]:
                raise InvalidToolArgument("changes.root_id", "Root identity is stable. Select the existing Root namespace; change name for a display rename.")
            if not created and args.get("expected_revision", existing[2]) != existing[2]:
                raise RevisionConflict(project_id, args["expected_revision"], existing[2])
            revision = existing[2]
            if not created and (changes or name is not None):
                manifest = self._management_manifest_changes(existing[3], changes) if changes else existing[3]
                cursor.execute("UPDATE collaboration_projects SET name=%s,context_manifest=%s,revision=revision+1 "
                               "WHERE tenant_id=%s AND project_id=%s",
                               (name or existing[4], canonical(manifest), self.context.tenant_id, project_id))
                revision += 1
            manager_result = None
            if manager is not None:
                if "principal_ref" not in manager:
                    cursor.execute("SELECT 1 FROM collaboration_team_members WHERE tenant_id=%s AND project_id=%s "
                                   "AND scope_id=%s AND agent_slot_id=%s",
                                   (self.context.tenant_id, project_id, existing[0], manager["agent_slot_id"]))
                    if cursor.fetchone() is None:
                        raise InvalidToolArgument("manager.principal_ref", "Provide the authenticated principal for a new Root manager; existing members retain theirs when omitted.")
                team_args = {"project_id": project_id, "scope_handle": handle("scope", project_id, existing[0]),
                             "members": [{**manager, "role": "root", "profile": "root_manager"}]}
                child = command.model_copy(update={"command_id": command.command_id + ":manager",
                    "idempotency_key": command.idempotency_key + ":manager", "command_type": "project.configure_team"})
                self._authorize(bound, cursor, project_id, "configure_team", team_args)
                manager_result = self._configure_team(bound, cursor, project, child, team_args, credential)
            record = self._management_record(bound, cursor, command, args, target_kind="root",
                target_id=existing[1], state="root.configured", revision=revision)
            result = ("configured", {"project_id": project_id, "root_handle": handle("project", project_id, existing[1]),
                "root_id": existing[1], "name": name or existing[4], "revision": revision,
                "configuration_state": "committed", "namespace_registered": created,
                "operation_id": record.operation_id, "manager_configuration": manager_result[1] if manager_result else None}, [])
            self._authorize(bound, cursor, project_id, "configure_root", args)
            self.service.authenticate(credential)
            if request_id:
                cursor.execute("INSERT INTO collaboration_commands(tenant_id,project_id,principal_ref,client_request_id,"
                               "tool_name,input_digest,command_id,result_json) VALUES (%s,%s,%s,%s,'configure_root',%s,%s,%s)",
                               (self.context.tenant_id, project_id, self.context.principal_ref, request_id,
                                input_digest, command.command_id, canonical(result)))
        if manager_result is not None and args.get("prepare_native", True):
            observed = self._prepare_communication_sessions(manager_result, {"project_id": project_id}, credential)
            result = (result[0], {**result[1], "manager_configuration": observed[1]}, result[2])
            if request_id:
                try:
                    with self.service.authority._connect() as connection:
                        connection.execute("UPDATE collaboration_commands SET result_json=%s WHERE tenant_id=%s AND project_id=%s "
                                           "AND principal_ref=%s AND client_request_id=%s",
                                           (canonical(result), self.context.tenant_id, project_id, self.context.principal_ref, request_id))
                except Exception:  # noqa: BLE001 - configuration already committed.
                    result = (result[0], {**result[1], "native_observation_retention": "unavailable"}, result[2])
        return result

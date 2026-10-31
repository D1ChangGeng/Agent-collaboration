"""Project configuration records and registered Scope lookup."""
from __future__ import annotations

from runtime.errors import NotFound
from runtime.models import CommandResult
from runtime.project_common import digest, parse_handle


class ManagementActions:
    def _management_record(self, authority, cursor, command, args, *, target_kind,
                           target_id, state, revision):
        command = command.model_copy(update={"target_kind": target_kind, "target_id": target_id})
        result = CommandResult(command_id=command.command_id,
            operation_id="op-" + digest([command.command_id, state]), target_id=target_id,
            revision=revision, state=state)
        duplicate, hashed = authority._dedup(cursor, command, result, args)
        if duplicate:
            raise ValueError("management command has an inconsistent projection")
        authority._operation(cursor, command, result.operation_id)
        authority._outbox(cursor, command, result.operation_id, state, {"project_id": args["project_id"]})
        cursor.execute("INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,to_state,initiated_by,"
                       "lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,"
                       "canonical_hash) VALUES (%s,%s,%s,%s,%s,%s,'external_command',%s,%s,'[]','v2',%s)",
                       (self.context.tenant_id, None,
                        target_kind, target_id, state, command.principal_ref,
                        command.command_id, revision, hashed))
        return result

    @staticmethod
    def _scope(cursor, tenant, project_id, scope_handle):
        scope_id = parse_handle(scope_handle, "scope", project_id)
        cursor.execute("SELECT scope_id FROM collaboration_projects WHERE tenant_id=%s "
                       "AND project_id=%s AND scope_id=%s UNION SELECT scope_id FROM collaboration_routes "
                       "WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                       (tenant, project_id, scope_id, tenant, project_id, scope_id))
        if not cursor.fetchone():
            raise NotFound("scope", scope_id)
        return scope_id

"""Resolve an already-authenticated uploader's exact private attachment viewer."""
from runtime.communication_attachment_storage import AttachmentIdentity
from runtime.errors import NotFound
from runtime.project_common import digest, parse_handle


def attachment_owner(cursor, context, project, address, root_scope):
    scope = root_scope
    if address.startswith("collaborator:"):
        slot = parse_handle(address, "collaborator", project)
        cursor.execute("SELECT scope_id FROM agent_slots WHERE tenant_id=%s AND agent_slot_id=%s AND status='active'",
                       (context.tenant_id, slot))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("attachment owner", address)
        scope = row[0]
    return AttachmentIdentity(context.tenant_id, project,
        "viewer-" + digest([context.tenant_id, project, context.principal_ref, address]), scope, address)

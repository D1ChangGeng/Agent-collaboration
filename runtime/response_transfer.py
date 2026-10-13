"""Copy verified terminal response bytes from the configured machine to its Scope CAS."""
from runtime.artifacts import ArtifactError
from runtime.source import SourceReadbackError


def ensure_response_artifacts(authority, store, *, project_id, message_id=None):
    if authority.access_mode != "owner" or store is None:
        return
    with authority._connect() as connection:
        rows = connection.execute(
            "SELECT m.operation_id,m.endpoint_id,m.packet_json->>'target_scope_id',"
            "r.evidence_json->>'response_digest',r.dispatch_id FROM delivery_messages m "
            "JOIN collaboration_work_links l ON l.tenant_id=m.tenant_id "
            "AND l.work_item_id=m.packet_json->>'work_item_id' "
            "JOIN collaboration_projects p ON p.tenant_id=l.tenant_id AND p.project_id=l.project_id "
            "JOIN delivery_receipts r ON r.tenant_id=m.tenant_id AND r.message_id=m.message_id "
            "WHERE m.tenant_id=%s AND l.project_id=%s AND p.state='active' "
            "AND r.layer='response_received' AND (%s::text IS NULL OR m.message_id=%s) "
            "ORDER BY r.observed_at DESC LIMIT 100", (authority.tenant_id,project_id,message_id,message_id)).fetchall()
        rows += connection.execute(
            "SELECT n.operation_id,n.endpoint_id,m.packet_json->>'target_scope_id',n.response_digest,n.dispatch_id "
            "FROM native_response_observations n JOIN delivery_messages m USING(tenant_id,message_id) "
            "JOIN collaboration_work_links l ON l.tenant_id=m.tenant_id AND l.work_item_id=m.packet_json->>'work_item_id' "
            "WHERE n.tenant_id=%s AND l.project_id=%s AND n.disposition='fenced_late' "
            "AND (%s::text IS NULL OR n.message_id=%s) ORDER BY n.observed_at DESC LIMIT 100",
            (authority.tenant_id,project_id,message_id,message_id)).fetchall()
    for operation,endpoint,scope,digest,dispatch in rows:
        provider = store.for_scope(scope) if hasattr(store,"for_scope") else store
        if provider.scope_id != scope:
            raise SourceReadbackError("response artifact Scope differs")
        try:
            provider.reference_for_digest(digest,kind="readback",media_type="application/json")
            continue
        except ArtifactError:
            pass
        adapter = authority._delivery_endpoints.get(endpoint)
        reader = getattr(adapter,"fetch_response_artifact",None)
        if not callable(reader):
            continue
        data = reader(operation,digest,max_bytes=provider.max_bytes,dispatch_id=dispatch)
        reference = provider.put_bytes(data,kind="readback",media_type="application/json")
        if reference.sha256 != digest:
            raise SourceReadbackError("copied response differs from its terminal receipt")

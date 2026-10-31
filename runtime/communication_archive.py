"""Explicit, additive operator adoption of known historical message associations."""
from __future__ import annotations

import hashlib
import json


def _exists(cursor, table):
    cursor.execute("SELECT to_regclass(%s)", (table,))
    return cursor.fetchone()[0] is not None


def _legacy_query(cursor):
    if not _exists(cursor, "collaboration_work_links"):
        return None
    tracking = _exists(cursor, "collaboration_response_tracking")
    response = "t.initiating_principal" if tracking else "NULL::text"
    join = ("LEFT JOIN collaboration_response_tracking t ON t.tenant_id=m.tenant_id "
            "AND t.project_id=l.project_id AND t.message_id=m.message_id " if tracking else "")
    return ("SELECT m.tenant_id,l.project_id,m.message_id,m.canonical_hash,m.command_json->>'principal_ref' AS principal_ref,"
        "m.packet_json->>'target_agent_slot_id' AS target_agent_slot_id,"+response+" AS initiating_principal FROM delivery_messages m "
        "JOIN collaboration_work_links l ON l.tenant_id=m.tenant_id AND l.work_item_id=m.packet_json->>'work_item_id' "
        +join+"WHERE m.tenant_id=%s AND m.packet_json->>'schema_version'='acs-delivery/1' "
        "AND (%s::text IS NULL OR l.project_id=%s) ORDER BY l.project_id,m.message_id")


def archive_plan(cursor, tenant_id, project_id=None):
    """Read-only facts. Missing identities remain unknown; no body inference."""
    query = _legacy_query(cursor)
    count = missing_author = missing_recipient = conflicts = 0
    hashed = hashlib.sha256()
    if query:
        cursor.execute(query, (tenant_id, project_id, project_id))
        while row := cursor.fetchone():
            count += 1
            missing_author += row[4] in {None, ""}
            missing_recipient += row[5] in {None, ""}
            hashed.update(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode())
            hashed.update(b"\n")
    adopted = _exists(cursor, "communication_archives")
    if adopted and query:
        cursor.execute("SELECT count(*) FROM ("+query+") source JOIN communication_archives a "
            "USING(tenant_id,project_id,message_id) WHERE "
            "(a.source_hash,a.author_principal_ref,a.recipient_slot_id,a.response_initiator_ref) IS DISTINCT FROM "
            "(source.canonical_hash,source.principal_ref,source.target_agent_slot_id,source.initiating_principal)",
            (tenant_id, project_id, project_id))
        conflicts = cursor.fetchone()[0]
    cursor.execute("SELECT packet_json->>'schema_version',count(*) FROM delivery_messages "
                   "WHERE tenant_id=%s GROUP BY packet_json->>'schema_version' ORDER BY 1", (tenant_id,))
    packet_counts = [{"schema": version, "count": total} for version, total in cursor.fetchall()]
    associations = []
    if _exists(cursor, "collaboration_work_links"):
        associations.append("EXISTS(SELECT 1 FROM collaboration_work_links l WHERE l.tenant_id=m.tenant_id "
                            "AND l.work_item_id=m.packet_json->>'work_item_id')")
    if adopted:
        associations.append("EXISTS(SELECT 1 FROM communication_archives a WHERE a.tenant_id=m.tenant_id AND a.message_id=m.message_id)")
    cursor.execute("SELECT count(*) FROM delivery_messages m WHERE m.tenant_id=%s "
        "AND m.packet_json->>'schema_version'='acs-delivery/1' AND NOT ("+
        (" OR ".join(associations) if associations else "FALSE")+")", (tenant_id,))
    unassociated = cursor.fetchone()[0]
    cursor.execute("SELECT state,count(*) FROM delivery_messages WHERE tenant_id=%s "
                   "AND state IN ('queued','retry_wait','delivering','uncertain') GROUP BY state ORDER BY state", (tenant_id,))
    retained = dict(cursor.fetchall())
    cursor.execute("SELECT count(*) FROM delivery_receipts WHERE tenant_id=%s AND layer='runtime_dispatched'", (tenant_id,))
    return {"mode": "dry_run", "tenant_id": tenant_id, "project_id": project_id,
        "archive_schema_adopted": adopted, "known_associations": count, "plan_sha256": hashed.hexdigest(),
        "author_principal_unknown": missing_author, "author_slot_unknown": count,
        "recipient_slot_unknown": missing_recipient, "recipient_principal_unknown": count,
        "tenant_legacy_without_project_association": unassociated,
        "conflicting_associations": conflicts, "tenant_packet_counts": packet_counts,
        "retained_delivery_states": retained, "retained_native_dispatch_fences": cursor.fetchone()[0],
        "effect": "Index stored project associations only; preserve packets, replies and recovery evidence."}


def adopt_legacy_index(cursor, tenant_id, project_id=None, *, expected_plan_sha256=None):
    """Explicit operator transaction; never called by a model tool or server startup."""
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("communication-archive:"+tenant_id,))
    plan = archive_plan(cursor, tenant_id, project_id)
    if expected_plan_sha256 is not None and plan["plan_sha256"] != expected_plan_sha256:
        raise ValueError("archive source changed after the dry run")
    if not plan["archive_schema_adopted"] or plan["conflicting_associations"]:
        raise ValueError("archive schema adoption or conflicting stored associations require operator review")
    query = _legacy_query(cursor)
    inserted = 0
    if query:
        cursor.execute("INSERT INTO communication_archives(tenant_id,project_id,message_id,source_schema,source_hash,"
            "author_principal_ref,recipient_slot_id,response_initiator_ref,association_source) "
            "SELECT tenant_id,project_id,message_id,'acs-delivery/1',canonical_hash,principal_ref,target_agent_slot_id,"
            "initiating_principal,'stored_project_work_link' FROM ("+query+
            ") source ON CONFLICT DO NOTHING", (tenant_id, project_id, project_id))
        inserted = cursor.rowcount
    return {**plan, "mode": "applied", "indexed_associations": inserted}

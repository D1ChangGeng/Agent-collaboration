"""Transactional event intent and post-commit ordered publication.

This internal store grants no read permission. Stream consumers must apply
current ProjectService tool/Grant/participant authorization before every emit.
Source rows contain references/revisions/ACL metadata, never message/draft text.
Source transactions never acquire a stream counter lock. A publisher locks that
counter first and copies only committed intents, so a late source transaction
cannot fall behind a snapshot's published high water.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, SchemaAdoptionError
from runtime.project_common import canonical

NAME, FILE, VERSION = "acs-communication-events", "communication_event_schema.sql", "1"
TABLES = ("communication_event_intents", "communication_event_clocks", "communication_event_stream")
TRIGGERS = {"acs_communication_message_events": ("communication_messages", 5, "acs_communication_message_events"),
    "acs_communication_reply_events": ("communication_replies", 5, "acs_communication_reply_events"),
    "acs_communication_delivery_events": ("communication_delivery_versions", 21, "acs_communication_delivery_events"),
    "acs_communication_read_events": ("communication_client_read_state", 21, "acs_communication_private_events"),
    "acs_communication_draft_events": ("communication_client_drafts", 21, "acs_communication_private_events")}
FIELDS = ("sequence", "event_id", "kind", "resource_ref", "resource_revision", "audience_kind", "sender", "recipient",
          "actor_ref", "scope_id", "payload_json", "committed_at", "published_at", "intent_id")
SHAPES = {
    TABLES[0]: {"intent_id": ("bigint", True), "tenant_id": ("text", True), "project_id": ("text", True),
        "source_key": ("text", True), "event_id": ("text", True), "kind": ("text", True), "resource_ref": ("text", False),
        "resource_revision": ("bigint", True), "audience_kind": ("text", True), "sender": ("text", False),
        "recipient": ("text", False), "actor_ref": ("text", False), "scope_id": ("text", False),
        "payload_json": ("jsonb", True), "committed_at": ("timestamp with time zone", True), "published_sequence": ("bigint", False)},
    TABLES[1]: {"tenant_id": ("text", True), "project_id": ("text", True), "high_water": ("bigint", True), "retained_through": ("bigint", True)},
    TABLES[2]: {"tenant_id": ("text", True), "project_id": ("text", True), "sequence": ("bigint", True),
        "intent_id": ("bigint", True), "event_id": ("text", True), "kind": ("text", True), "resource_ref": ("text", False),
        "resource_revision": ("bigint", True), "audience_kind": ("text", True), "sender": ("text", False),
        "recipient": ("text", False), "actor_ref": ("text", False), "scope_id": ("text", False),
        "payload_json": ("jsonb", True), "committed_at": ("timestamp with time zone", True), "published_at": ("timestamp with time zone", True)},
}
PRIMARY_KEYS = {TABLES[0]: ("intent_id",), TABLES[1]: ("tenant_id", "project_id"), TABLES[2]: ("tenant_id", "project_id", "sequence")}
UNIQUE_KEYS = {TABLES[0]: {("tenant_id", "project_id", "source_key"), ("event_id",), ("tenant_id", "project_id", "intent_id"), ("tenant_id", "project_id", "published_sequence")},
    TABLES[1]: set(), TABLES[2]: {("intent_id",), ("event_id",)}}
KINDS = frozenset({"message.committed", "reply.linked", "delivery.changed", "receiver.observed", "capability.changed",
    "notice.created", "notice.updated", "conversation.updated", "read_state.changed", "draft.changed", "attachment.ready",
    "native_link.changed", "permission.changed", "resync.required", "stream.end"})
AUDIENCES = frozenset({"message", "private", "conversation", "receiver", "notice", "control"})
log = logging.getLogger(__name__)


class EventCursorExpired(ValueError):
    code = "cursor_expired"


def _shape(connection, checksum):
    for table in TABLES:
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing event relation")
        rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in rows} != SHAPES[table]:
            raise SchemaAdoptionError(NAME, checksum, "damaged event columns")
        indexes = connection.execute("SELECT i.indisprimary,ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) "
            "FROM pg_index i WHERE i.indrelid=to_regclass(%s) AND i.indisvalid AND i.indisready AND i.indislive "
            "AND i.indisunique AND i.indpred IS NULL", (table,)).fetchall()
        if [tuple(row[1]) for row in indexes if row[0]] != [PRIMARY_KEYS[table]]:
            raise SchemaAdoptionError(NAME, checksum, "damaged event primary key")
        if not UNIQUE_KEYS[table] <= {tuple(row[1]) for row in indexes}:
            raise SchemaAdoptionError(NAME, checksum, "missing event identity fence")
    source, _checksum, _equivalents = schema_definition(FILE, VERSION)
    functions = dict(re.findall(r"CREATE FUNCTION ([a-z_]+)\([^;]*?\)\s*RETURNS (?:VOID|trigger) LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
                               source.decode("utf-8"), re.DOTALL))
    for name, expected_body in functions.items():
        row = connection.execute("SELECT p.prosrc,p.prosecdef,p.provolatile FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=%s", (name,)).fetchall()
        if len(row) != 1 or row[0][0].strip() != expected_body.strip() or row[0][1] is not False or row[0][2] != "v":
            raise SchemaAdoptionError(NAME, checksum, "damaged event producer function")
    for trigger, (table, kind, function) in TRIGGERS.items():
        row = connection.execute("SELECT t.tgenabled,t.tgtype,t.tgfoid=to_regprocedure(%s),cardinality(t.tgattr::smallint[]) FROM pg_trigger t "
            "WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal", (function + "()", trigger, table)).fetchone()
        if row is None or row[0] not in {"O", "A"} or row[1] != kind or row[2] is not True or row[3] != 0:
            raise SchemaAdoptionError(NAME, checksum, "missing event source trigger")
    pending = connection.execute("SELECT i.indisvalid AND i.indisready AND i.indislive,pg_get_expr(i.indpred,i.indrelid),"
        "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indexrelid=to_regclass('communication_event_pending') AND i.indrelid=to_regclass('communication_event_intents')").fetchone()
    if pending is None or pending[0] is not True or pending[1] != "(published_sequence IS NULL)" or pending[2] != ["tenant_id", "project_id", "intent_id"]:
        raise SchemaAdoptionError(NAME, checksum, "missing event publisher index")
    expiry = connection.execute("SELECT i.indisvalid AND i.indisready AND i.indislive,"
        "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indexrelid=to_regclass('communication_event_expiry') AND i.indrelid=to_regclass('communication_event_stream')").fetchone()
    if expiry is None or expiry[0] is not True or expiry[1] != ["tenant_id", "project_id", "published_at", "sequence"]:
        raise SchemaAdoptionError(NAME, checksum, "missing event retention index")
    if connection.execute("SELECT 1 FROM communication_event_stream s LEFT JOIN communication_event_clocks c "
        "USING(tenant_id,project_id) WHERE c.high_water IS NULL OR s.sequence>c.high_water OR s.sequence<=c.retained_through LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "inconsistent event stream boundary")
    if connection.execute("SELECT 1 FROM communication_event_clocks c LEFT JOIN communication_event_stream s "
        "USING(tenant_id,project_id) GROUP BY c.tenant_id,c.project_id,c.high_water,c.retained_through "
        "HAVING count(s.sequence)<>c.high_water-c.retained_through LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "missing retained event stream record")
    if connection.execute("SELECT 1 FROM communication_event_intents i LEFT JOIN communication_event_clocks c USING(tenant_id,project_id) "
        "LEFT JOIN communication_event_stream s ON s.intent_id=i.intent_id WHERE i.published_sequence IS NOT NULL AND "
        "(c.high_water IS NULL OR i.published_sequence>c.high_water OR (i.published_sequence>c.retained_through AND "
        "(s.sequence IS NULL OR s.sequence<>i.published_sequence))) LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "inconsistent published event intent")
    if connection.execute("SELECT 1 FROM communication_event_stream s JOIN communication_event_intents i USING(intent_id) "
        "WHERE ROW(s.tenant_id,s.project_id,s.event_id,s.kind,s.resource_ref,s.resource_revision,s.audience_kind,s.sender,s.recipient,"
        "s.actor_ref,s.scope_id,s.payload_json,s.committed_at,s.sequence) IS DISTINCT FROM "
        "ROW(i.tenant_id,i.project_id,i.event_id,i.kind,i.resource_ref,i.resource_revision,i.audience_kind,i.sender,i.recipient,"
        "i.actor_ref,i.scope_id,i.payload_json,i.committed_at,i.published_sequence) LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "event publication differs from its source fact")


def adopt_event_storage(connection):
    from runtime.communication_client_storage import verify_client_storage

    verify_client_storage(connection)
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-events:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is not None:
        if row not in equivalents:
            raise SchemaAdoptionError(NAME, checksum, "explicit event migration required")
    else:
        if any(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None for table in TABLES):
            raise SchemaAdoptionError(NAME, checksum, "unversioned event storage")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    _shape(connection, checksum)


def verify_event_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "event storage adoption required")
    _shape(connection, checksum)


def record_event_intent(cursor, tenant, project, *, source_key, kind, resource_ref, resource_revision,
                        audience_kind, sender=None, recipient=None, actor_ref=None, scope_id=None, payload=None):
    if type(resource_revision) is not int or not 0 <= resource_revision <= 2**63 - 1:
        raise ValueError("invalid event resource revision")
    if any(type(value) is not str or not 1 <= len(value) <= 512 for value in (tenant, project, source_key)):
        raise ValueError("invalid event identity")
    if kind not in KINDS or audience_kind not in AUDIENCES:
        raise ValueError("invalid event kind or audience")
    for value in (resource_ref, sender, recipient, actor_ref, scope_id):
        if value is not None and (type(value) is not str or not 1 <= len(value) <= 512):
            raise ValueError("invalid event metadata reference")
    payload = {} if payload is None else payload
    if (type(payload) is not dict or set(payload) - {"reason_code", "message_handle", "conversation_id", "operation_ref", "reset_required"}
            or len(canonical(payload).encode()) > 8192):
        raise ValueError("event payload contains unsupported data")
    for key, value in payload.items():
        if key == "reset_required":
            if type(value) is not bool:
                raise ValueError("invalid event reset signal")
        elif type(value) is not str or (key != "reason_code" and not 1 <= len(value) <= 512):
            raise ValueError("invalid event metadata payload")
    try:
        cursor.execute("SELECT acs_communication_event_intent(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant, project, source_key, kind, resource_ref, resource_revision, audience_kind, sender, recipient, actor_ref, scope_id, canonical(payload)))
    except Exception as error:  # SQL identity conflict is a failed source transaction, never a partial publication.
        if getattr(error, "sqlstate", None) == "P0001" and "communication_event_intent_identity_conflict" in str(error):
            raise IdempotencyConflict(source_key) from error
        raise


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("event batch limit must be between 1 and 1000")


def publish_event_intents(connection, tenant, project, *, limit=100):
    """Caller owns the short transaction; rollback retains every original intent."""
    _limit(limit)
    connection.execute("INSERT INTO communication_event_clocks(tenant_id,project_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (tenant, project))
    high = connection.execute("SELECT high_water FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s FOR UPDATE", (tenant, project)).fetchone()[0]
    rows = connection.execute("SELECT intent_id,event_id,kind,resource_ref,resource_revision,audience_kind,sender,recipient,actor_ref,scope_id,payload_json,committed_at "
        "FROM communication_event_intents WHERE tenant_id=%s AND project_id=%s AND published_sequence IS NULL "
        "ORDER BY intent_id LIMIT %s FOR UPDATE SKIP LOCKED", (tenant, project, limit)).fetchall()
    for row in rows:
        high += 1
        connection.execute("INSERT INTO communication_event_stream(tenant_id,project_id,sequence,intent_id,event_id,kind,resource_ref,"
            "resource_revision,audience_kind,sender,recipient,actor_ref,scope_id,payload_json,committed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant, project, high, *row[:10], canonical(row[10]), row[11]))
        connection.execute("UPDATE communication_event_intents SET published_sequence=%s WHERE intent_id=%s AND published_sequence IS NULL", (high, row[0]))
    if rows:
        connection.execute("UPDATE communication_event_clocks SET high_water=%s WHERE tenant_id=%s AND project_id=%s", (high, tenant, project))
    return len(rows)


def stream_high_water(cursor, tenant, project):
    cursor.execute("SELECT high_water FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s", (tenant, project))
    row = cursor.fetchone()
    return row[0] if row else 0


def read_event_records(cursor, tenant, project, *, after, limit=100):
    _limit(limit)
    if type(after) is not int or not 0 <= after <= 2**63 - 1:
        raise ValueError("invalid event replay position")
    cursor.execute("SELECT high_water,retained_through FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s FOR SHARE", (tenant, project))
    boundary = cursor.fetchone()
    if boundary is None:
        if after:
            raise ValueError("event cursor is ahead of this stream")
        return []  # Linearize before a concurrent first publication; do not mix a later stream view.
    if after < boundary[1]:
        raise EventCursorExpired("event cursor precedes the retained replay boundary")
    if after > boundary[0]:
        raise ValueError("event cursor is ahead of this stream")
    cursor.execute("SELECT " + ",".join(FIELDS) + " FROM communication_event_stream WHERE tenant_id=%s AND project_id=%s "
                   "AND sequence>%s ORDER BY sequence LIMIT %s", (tenant, project, after, limit))
    return [dict(zip(FIELDS, row, strict=True)) for row in cursor.fetchall()]


def purge_event_records(connection, tenant, project, *, before, limit=1000):
    """Delete only an expired contiguous prefix; keep source dedup tombstones."""
    if not isinstance(before, datetime) or before.tzinfo is None or before.utcoffset() is None:
        raise ValueError("event retention cutoff must be an aware instant")
    _limit(limit)
    boundary = connection.execute("SELECT high_water,retained_through FROM communication_event_clocks "
        "WHERE tenant_id=%s AND project_id=%s FOR UPDATE", (tenant, project)).fetchone()
    if boundary is None:
        return 0, 0
    first_retained = connection.execute("SELECT min(sequence) FROM communication_event_stream WHERE tenant_id=%s AND project_id=%s "
        "AND published_at>=%s", (tenant, project, before)).fetchone()[0]
    floor = boundary[0] if first_retained is None else first_retained - 1
    floor = max(floor, boundary[1])
    candidates = connection.execute("SELECT sequence FROM communication_event_stream WHERE tenant_id=%s AND project_id=%s "
        "AND sequence<=%s ORDER BY sequence LIMIT %s", (tenant, project, floor, limit)).fetchall()
    floor = candidates[-1][0] if candidates else boundary[1]
    removed = connection.execute("DELETE FROM communication_event_stream WHERE tenant_id=%s AND project_id=%s AND sequence<=%s", (tenant, project, floor)).rowcount
    connection.execute("UPDATE communication_event_clocks SET retained_through=%s WHERE tenant_id=%s AND project_id=%s", (floor, tenant, project))
    return removed, floor


def maintain_event_publication(authority, *, project_limit=16, batch_limit=100):
    """Bounded control-plane projection; independent of a connected UI."""
    if not (getattr(authority, "_communication_events_enabled", False)
            or getattr(authority, "_communication_event_storage_available", False)):
        return 0
    if type(project_limit) is not int or not 1 <= project_limit <= 64:
        raise ValueError("invalid event maintenance project limit")
    _limit(batch_limit)
    with authority._connect() as connection:
        projects = connection.execute("SELECT project_id FROM (SELECT DISTINCT project_id FROM communication_event_intents WHERE tenant_id=%s "
            "AND published_sequence IS NULL) candidates ORDER BY (project_id>%s) DESC,project_id LIMIT %s",
            (authority.tenant_id, getattr(authority, "_event_publication_after", ""), project_limit)).fetchall()
    if projects:
        authority._event_publication_after = projects[-1][0]
    published = 0
    for (project,) in projects:
        try:
            with authority._connect() as connection:
                published += publish_event_intents(connection, authority.tenant_id, project, limit=batch_limit)
        except Exception as error:  # noqa: BLE001 - one project cannot starve other committed event streams.
            log.warning("Event publication unavailable: %s", type(error).__name__)
    return published


def maintain_event_retention(authority, *, project_limit=16, retention_seconds=7 * 86400):
    if not (getattr(authority, "_communication_events_enabled", False)
            or getattr(authority, "_communication_event_storage_available", False)):
        return 0
    if type(project_limit) is not int or not 1 <= project_limit <= 64 or type(retention_seconds) is not int or retention_seconds < 1:
        raise ValueError("invalid event retention budget")
    with authority._connect() as connection:
        projects = connection.execute("SELECT c.project_id FROM communication_event_clocks c WHERE c.tenant_id=%s "
            "AND EXISTS(SELECT 1 FROM communication_event_stream s WHERE s.tenant_id=c.tenant_id AND s.project_id=c.project_id "
            "AND s.published_at<clock_timestamp()-%s*interval '1 second') ORDER BY (c.project_id>%s) DESC,c.project_id LIMIT %s",
            (authority.tenant_id, retention_seconds, getattr(authority, "_event_retention_after", ""), project_limit)).fetchall()
    if projects:
        authority._event_retention_after = projects[-1][0]
    removed = 0
    for (project,) in projects:
        try:
            with authority._connect() as connection:
                cutoff = connection.execute("SELECT clock_timestamp()-%s*interval '1 second'", (retention_seconds,)).fetchone()[0]
                count, _floor = purge_event_records(connection, authority.tenant_id, project, before=cutoff)
                removed += count
        except Exception as error:  # noqa: BLE001 - preserve independent project cleanup and all source history.
            log.warning("Event retention unavailable: %s", type(error).__name__)
    return removed

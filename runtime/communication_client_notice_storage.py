"""Explicit notice projection adoption and actor-private seen CAS/receipts.

The service must establish actual recipient ACL before these storage helpers.
They neither read message bodies nor create Native acknowledgments or replies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, RevisionConflict, SchemaAdoptionError
from runtime.project_common import canonical, digest

NAME, FILE, VERSION = "acs-communication-client-notices", "communication_client_notice_schema.sql", "1"
TABLES = ("communication_client_notice_versions", "communication_client_notice_seen", "communication_client_notice_write_keys")
TRIGGERS = {"acs_client_notice_source_version": ("communication_notices", 21),
    "acs_client_notice_route_version": ("communication_notice_routes", 21),
    "acs_client_notice_delivery_version": ("communication_delivery_versions", 21)}
SHAPES = {
    TABLES[0]: {"tenant_id": ("text", True), "project_id": ("text", True), "message_id": ("text", True),
        "notice_ref": ("text", True),
        "recipient": ("text", True), "revision": ("bigint", True), "created_at": ("timestamp with time zone", False)},
    TABLES[1]: {"tenant_id": ("text", True), "project_id": ("text", True), "actor_ref": ("text", True),
        "message_id": ("text", True), "recipient": ("text", True), "seen": ("boolean", True),
        "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True)},
    TABLES[2]: {"tenant_id": ("text", True), "actor_ref": ("text", True), "client_request_id": ("text", True),
        "canonical_hash": ("text", True), "result_json": ("jsonb", True), "created_at": ("timestamp with time zone", True)},
}
PRIMARY_KEYS = {TABLES[0]: ("tenant_id", "project_id", "message_id", "recipient"),
    TABLES[1]: ("tenant_id", "project_id", "actor_ref", "message_id", "recipient"),
    TABLES[2]: ("tenant_id", "actor_ref", "client_request_id")}


def _shape(connection, checksum):
    for table in TABLES:
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing notice projection relation")
        rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in rows} != SHAPES[table]:
            raise SchemaAdoptionError(NAME, checksum, "damaged notice projection columns")
        rows = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n),"
            "i.indisvalid AND i.indisready AND i.indislive AND i.indisunique FROM pg_index i "
            "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary", (table,)).fetchall()
        if len(rows) != 1 or tuple(rows[0][0]) != PRIMARY_KEYS[table] or rows[0][1] is not True:
            raise SchemaAdoptionError(NAME, checksum, "damaged notice projection primary key")
    source, _checksum, _equivalents = schema_definition(FILE, VERSION)
    opaque = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indrelid=to_regclass(%s) AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive AND i.indpred IS NULL", (TABLES[0],)).fetchall()
    if (["tenant_id", "project_id", "notice_ref"],) not in opaque:
        raise SchemaAdoptionError(NAME, checksum, "missing opaque notice identity fence")
    functions = dict(re.findall(r"CREATE FUNCTION ([a-z_]+)\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;", source.decode("utf-8"), re.DOTALL))
    for trigger, (table, events) in TRIGGERS.items():
        row = connection.execute("SELECT t.tgenabled,t.tgtype,t.tgfoid=to_regprocedure(%s),"
            "ARRAY(SELECT a.attname FROM pg_attribute a WHERE a.attrelid=t.tgrelid AND a.attnum=ANY(t.tgattr) ORDER BY a.attname),"
            "p.prosrc,p.prosecdef,p.provolatile FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal", (trigger + "()", trigger, table)).fetchone()
        columns = ["code", "state"] if trigger == "acs_client_notice_source_version" else []
        if (row is None or row[0] not in {"O", "A"} or row[1] != events or row[2] is not True or row[3] != columns
                or row[4].strip() != functions[trigger].strip() or row[5] is not False or row[6] != "v"):
            raise SchemaAdoptionError(NAME, checksum, "missing notice projection trigger")
    index = connection.execute("SELECT i.indisvalid AND i.indisready AND i.indislive,"
        "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indexrelid=to_regclass('communication_client_notice_page') AND i.indrelid=to_regclass('communication_notices')").fetchone()
    if index is None or index[0] is not True or index[1] != ["tenant_id", "project_id", "recipient", "sequence"]:
        raise SchemaAdoptionError(NAME, checksum, "missing notice page index")
    for table, target in ((TABLES[0], "communication_notices"), (TABLES[1], TABLES[0])):
        keys = ["tenant_id", "project_id", "message_id", "recipient"]
        rows = connection.execute("SELECT c.confrelid=to_regclass(%s),c.convalidated,c.confdeltype,"
            "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),"
            "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
            "WHERE c.conrelid=to_regclass(%s) AND c.contype='f'", (target, table)).fetchall()
        if rows != [(True, True, "c", keys, keys)]:
            raise SchemaAdoptionError(NAME, checksum, "damaged notice source foreign key")
    # Removing a materialized source row must fail closed rather than reset CAS.
    if connection.execute("SELECT 1 FROM communication_notices n LEFT JOIN communication_client_notice_versions v "
        "USING(tenant_id,project_id,message_id,recipient) WHERE v.revision IS NULL LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "missing notice source version")
    if connection.execute("SELECT 1 FROM communication_notice_routes r LEFT JOIN communication_delivery_versions v "
        "ON v.tenant_id=r.tenant_id AND v.message_id=r.delivery_message_id "
        "WHERE r.delivery_message_id IS NOT NULL AND v.revision IS NULL LIMIT 1").fetchone():
        raise SchemaAdoptionError(NAME, checksum, "missing routed notice delivery projection")


def adopt_notice_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-client-notices:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is not None:
        if row not in equivalents:
            raise SchemaAdoptionError(NAME, checksum, "explicit notice projection migration required")
    else:
        if any(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None for table in TABLES):
            raise SchemaAdoptionError(NAME, checksum, "unversioned notice projection")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    _shape(connection, checksum)


def verify_notice_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "notice projection adoption required")
    _shape(connection, checksum)


@dataclass(frozen=True, slots=True)
class NoticeStateIdentity:
    tenant_id: str
    project_id: str
    actor_ref: str
    message_id: str
    recipient: str

    def __post_init__(self):
        if any(type(value) is not str or not value or len(value) > 512 for value in self.values()):
            raise ValueError("invalid notice state identity")

    def source(self):
        return self.tenant_id, self.project_id, self.message_id, self.recipient

    def values(self):
        return self.tenant_id, self.project_id, self.actor_ref, self.message_id, self.recipient


def read_notice_metadata(cursor, identity):
    cursor.execute("SELECT r.delivery_message_id,v.revision FROM communication_client_notice_versions v "
        "LEFT JOIN communication_notice_routes r USING(tenant_id,project_id,message_id,recipient) "
        "WHERE v.tenant_id=%s AND v.project_id=%s AND v.message_id=%s AND v.recipient=%s", identity.source())
    selected = cursor.fetchone()
    if selected is None:
        raise LookupError("notice source projection not materialized")
    delivery = selected[0] if selected else None
    if delivery is not None:
        cursor.execute("SELECT revision FROM communication_delivery_versions WHERE tenant_id=%s AND message_id=%s FOR SHARE", (identity.tenant_id, delivery))
        if cursor.fetchone() is None:
            raise LookupError("notice delivery projection not materialized")
    cursor.execute("SELECT revision,created_at FROM communication_client_notice_versions WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s FOR SHARE", identity.source())
    row = cursor.fetchone()
    if row is None:
        raise LookupError("notice source projection not materialized")
    cursor.execute("SELECT delivery_message_id FROM communication_notice_routes WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", identity.source())
    after = cursor.fetchone()
    if (after[0] if after else None) != delivery:
        raise RevisionConflict(identity.message_id, selected[1], row[0], guidance="Notice route changed; read the current view again.")
    return row[0], row[1].isoformat() if row[1] else None


def read_notice_seen(cursor, identity):
    cursor.execute("SELECT seen,revision FROM communication_client_notice_seen WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND message_id=%s AND recipient=%s", identity.values())
    return cursor.fetchone() or (False, 0)


def notice_public_ref(cursor, identity):
    cursor.execute("SELECT notice_ref FROM communication_client_notice_versions WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", identity.source())
    row = cursor.fetchone()
    if row is None:
        raise LookupError("notice source projection not materialized")
    return row[0]


def write_notice_seen(cursor, identity, seen, *, expected_revision, client_request_id, project_result, revision_reader=None):
    if type(seen) is not bool or type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 2:
        raise ValueError("invalid notice seen update")
    if type(client_request_id) is not str or not 1 <= len(client_request_id) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in client_request_id):
        raise ValueError("invalid stable notice write key")
    canonical_hash = digest([identity.source(), seen, expected_revision])
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (canonical([NAME, identity.tenant_id, identity.actor_ref, client_request_id]),))
    cursor.execute("SELECT canonical_hash,result_json FROM communication_client_notice_write_keys WHERE tenant_id=%s AND actor_ref=%s AND client_request_id=%s", (identity.tenant_id, identity.actor_ref, client_request_id))
    previous = cursor.fetchone()
    if previous is not None:
        if previous[0] != canonical_hash:
            raise IdempotencyConflict(client_request_id)
        return previous[1]
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (canonical([NAME, identity.values()]),))
    source_revision, created_at = read_notice_metadata(cursor, identity)
    _seen, revision = read_notice_seen(cursor, identity)
    actual_revision = revision_reader(cursor, identity, source_revision, revision) if revision_reader else source_revision + revision
    if actual_revision != expected_revision:
        raise RevisionConflict(identity.message_id, expected_revision, actual_revision, field="If-Match")
    cursor.execute("INSERT INTO communication_client_notice_seen(tenant_id,project_id,actor_ref,message_id,recipient,seen,revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,project_id,actor_ref,message_id,recipient) DO UPDATE "
        "SET seen=EXCLUDED.seen,revision=EXCLUDED.revision,updated_at=clock_timestamp()", (*identity.values(), seen, revision + 1))
    result = project_result(seen, revision + 1, source_revision, created_at)
    cursor.execute("INSERT INTO communication_client_notice_write_keys(tenant_id,actor_ref,client_request_id,canonical_hash,result_json) VALUES (%s,%s,%s,%s,%s)",
        (identity.tenant_id, identity.actor_ref, client_request_id, canonical_hash, canonical(result)))
    return result


def notice_page_version(cursor, tenant, project, recipient, actor_ref):
    cursor.execute("SELECT count(*),COALESCE(max(n.sequence),0),COALESCE(sum(v.revision),0)::text,COALESCE(sum(s.revision),0)::text "
        "FROM communication_notices n JOIN communication_client_notice_versions v USING(tenant_id,project_id,message_id,recipient) "
        "LEFT JOIN communication_client_notice_seen s ON (s.tenant_id,s.project_id,s.message_id,s.recipient)="
        "(n.tenant_id,n.project_id,n.message_id,n.recipient) AND s.actor_ref=%s "
        "WHERE n.tenant_id=%s AND n.project_id=%s AND n.recipient=%s", (actor_ref, tenant, project, recipient))
    return digest(cursor.fetchone())

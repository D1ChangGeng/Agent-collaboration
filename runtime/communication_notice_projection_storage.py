"""Serialized viewer-specific Notice revisions, independent of source/seen counters."""
from __future__ import annotations

import re

from runtime.communication_client_notice_storage import read_notice_metadata, read_notice_seen
from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-notice-projections", "communication_notice_projection_schema.sql", "1"
TABLE = "communication_notice_view_versions"


def _shape(connection, checksum):
    rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
        "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (TABLE,)).fetchall()
    expected = {name: ("text", True) for name in ("tenant_id", "project_id", "message_id", "recipient", "actor_ref")}
    expected.update({name: ("bigint", True) for name in ("source_revision", "seen_revision", "revision")})
    if {name: (kind, required) for name, kind, required in rows} != expected:
        raise SchemaAdoptionError(NAME, checksum, "damaged notice viewer projection columns")
    key = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i WHERE "
        "i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (TABLE,)).fetchall()
    if key != [(["tenant_id", "project_id", "message_id", "recipient", "actor_ref"],)]:
        raise SchemaAdoptionError(NAME, checksum, "damaged notice viewer projection key")
    bodies = dict(re.findall(r"CREATE FUNCTION ([a-z_]+)\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
                            schema_definition(FILE, VERSION)[0].decode(), re.DOTALL))
    for name, table in (("acs_notice_projection_source", "communication_client_notice_versions"),
                        ("acs_notice_projection_seen", "communication_client_notice_seen")):
        row = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure(%s),p.prosrc,p.prosecdef,p.provolatile "
            "FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal",
            (name + "()", name, table)).fetchone()
        events = 29 if name == "acs_notice_projection_seen" else 21
        if row is None or row[0] != events or row[1] not in {"O", "A"} or row[2] is not True or row[3].strip() != bodies[name].strip() or row[4:] != (False, "v"):
            raise SchemaAdoptionError(NAME, checksum, "damaged notice viewer source hook")


def adopt_notice_projection_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-notice-projections:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None:
            raise SchemaAdoptionError(NAME, checksum, "unversioned notice viewer projection")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit notice viewer projection migration required")
    _shape(connection, checksum)


def verify_notice_projection_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "notice viewer projection adoption required")
    _shape(connection, checksum)


def sync_notice_projection(cursor, identity):
    # Technical delivery -> public notice -> viewer counter, then MVCC seen.
    # A concurrent seen writer cannot commit its row until it updates this counter.
    source_revision, _created_at = read_notice_metadata(cursor, identity)
    cursor.execute("INSERT INTO communication_notice_view_versions(tenant_id,project_id,message_id,recipient,actor_ref,source_revision,seen_revision,revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,0,%s) ON CONFLICT DO NOTHING", (*identity.source(), identity.actor_ref, source_revision, source_revision))
    cursor.execute("SELECT source_revision,seen_revision,revision FROM communication_notice_view_versions WHERE "
        "tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s AND actor_ref=%s FOR UPDATE", (*identity.source(), identity.actor_ref))
    old_source, old_seen, revision = cursor.fetchone()
    _seen, seen_revision = read_notice_seen(cursor, identity)
    new_source, new_seen = max(source_revision, old_source), max(seen_revision, old_seen)
    if (new_source, new_seen) != (old_source, old_seen):
        revision += new_source - old_source + new_seen - old_seen
        cursor.execute("UPDATE communication_notice_view_versions SET source_revision=%s,seen_revision=%s,revision=%s WHERE "
            "tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s AND actor_ref=%s",
            (new_source, new_seen, revision, *identity.source(), identity.actor_ref))
    return revision


def notice_projection_revision(cursor, identity):
    cursor.execute("SELECT revision FROM communication_notice_view_versions WHERE tenant_id=%s AND project_id=%s "
        "AND message_id=%s AND recipient=%s AND actor_ref=%s", (*identity.source(), identity.actor_ref))
    row = cursor.fetchone()
    if row is None:
        raise LookupError("notice viewer projection is not materialized")
    return row[0]


def notice_cas_revision(cursor, identity, source_revision, seen_revision):
    # Caller already holds the public source fence and actor mutation advisory
    # lock. Do not take a view lock before writing the source seen cell.
    cursor.execute("SELECT revision FROM communication_notice_view_versions WHERE tenant_id=%s AND project_id=%s "
        "AND message_id=%s AND recipient=%s AND actor_ref=%s", (*identity.source(), identity.actor_ref))
    row = cursor.fetchone()
    return row[0] if row else source_revision + seen_revision

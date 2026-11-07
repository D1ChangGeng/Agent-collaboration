"""Explicit operator ownership adoption; no public management/private-read bypass.

Historical principal-only rows cannot prove which same-principal Slot owned a
draft. Reads fail closed until an operator supplies an actual ownership decision.
Adoption copies exact state/version/timestamp to that viewer, retains originals
and old receipts, and fences retired writers. Stop the older HTTP feature before
the operator step; an unpatched reader cannot be made safe by a write trigger.
"""
from __future__ import annotations

import re

from psycopg import sql

from runtime.communication_client_storage import SHAPES, ClientStateIdentity, _lock
from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-client-viewer-ownership", "communication_client_viewer_schema.sql", "1"
TABLE = "communication_client_viewer_adoptions"
RESOURCES = (("communication_client_read_state", "read_state"),
             ("communication_client_preferences", "preferences"), ("communication_client_drafts", "draft"))
TRIGGERS = ("acs_client_retired_read_viewer", "acs_client_retired_preferences_viewer", "acs_client_retired_draft_viewer")


def _shape(connection, checksum):
    if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
        raise SchemaAdoptionError(NAME, checksum, "missing viewer ownership decisions")
    expected = {"tenant_id": ("text", True), "project_id": ("text", True), "legacy_actor_ref": ("text", True),
        "conversation_id": ("text", True), "viewer_actor_ref": ("text", True), "decision_ref": ("text", True),
        "adopted_at": ("timestamp with time zone", True)}
    rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
        "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (TABLE,)).fetchall()
    if {name: (kind, required) for name, kind, required in rows} != expected:
        raise SchemaAdoptionError(NAME, checksum, "damaged viewer ownership columns")
    key = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (TABLE,)).fetchall()
    if key != [(["tenant_id", "project_id", "legacy_actor_ref", "conversation_id"],)]:
        raise SchemaAdoptionError(NAME, checksum, "damaged viewer ownership decision key")
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    expected_body = source.split("AS $$", 1)[1].split("$$;", 1)[0].strip()
    function = connection.execute("SELECT prosrc,prosecdef,provolatile FROM pg_proc "
        "WHERE oid=to_regprocedure('acs_client_retired_viewer_guard()')").fetchone()
    if function is None or function[0].strip() != expected_body or function[1] is not False or function[2] != "v":
        raise SchemaAdoptionError(NAME, checksum, "damaged retired viewer guard")
    for trigger, (table, _kind) in zip(TRIGGERS, RESOURCES, strict=True):
        row = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure('acs_client_retired_viewer_guard()'),cardinality(t.tgattr::smallint[]) "
            "FROM pg_trigger t WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal", (trigger, table)).fetchone()
        if row is None or row[0] != 23 or row[1] not in {"O", "A"} or row[2] is not True or row[3] != 0:
            raise SchemaAdoptionError(NAME, checksum, "missing retired viewer writer fence")


def adopt_viewer_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-viewer-ownership:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None:
            raise SchemaAdoptionError(NAME, checksum, "unversioned viewer ownership decisions")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit viewer ownership migration required")
    _shape(connection, checksum)


def verify_viewer_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "viewer ownership adoption required")
    _shape(connection, checksum)


def require_personal_owner(cursor, identity, legacy_actor_ref):
    if legacy_actor_ref == identity.actor_ref:
        return
    for table, _kind in RESOURCES:
        cursor.execute(sql.SQL("SELECT 1 FROM {} WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s").format(sql.Identifier(table)),
                       (identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id))
        if cursor.fetchone() is not None:
            cursor.execute("SELECT to_regclass(%s)", (TABLE,))
            if cursor.fetchone()[0] is not None:
                cursor.execute("SELECT 1 FROM communication_client_viewer_adoptions WHERE tenant_id=%s AND project_id=%s "
                    "AND legacy_actor_ref=%s AND conversation_id=%s", (identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id))
                if cursor.fetchone() is not None:
                    return  # Decision assigned it explicitly; other viewers get their own independent state.
            raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "principal-only state needs an explicit viewer ownership decision")


def adopt_legacy_personal_state(cursor, identity, *, legacy_actor_ref, decision_ref):
    """Trusted operator cursor and explicit ownership decision, never a read API."""
    if not isinstance(identity, ClientStateIdentity) or re.fullmatch(r"viewer-[a-f0-9]{64}", identity.actor_ref) is None:
        raise ValueError("an explicit scoped viewer identity is required")
    if any(type(value) is not str or not 1 <= len(value) <= 512 for value in (legacy_actor_ref, decision_ref)) or legacy_actor_ref == identity.actor_ref:
        raise ValueError("invalid explicit ownership decision")
    _lock(cursor, NAME, [identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id])
    cursor.execute("SELECT viewer_actor_ref,decision_ref FROM communication_client_viewer_adoptions WHERE tenant_id=%s AND project_id=%s "
        "AND legacy_actor_ref=%s AND conversation_id=%s", (identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id))
    previous = cursor.fetchone()
    if previous:
        if previous != (identity.actor_ref, decision_ref):
            raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "viewer ownership decision conflicts")
        return
    for table, kind in RESOURCES:
        for actor in sorted((legacy_actor_ref, identity.actor_ref)):
            _lock(cursor, "acs-client-state", [identity.tenant_id, identity.project_id, actor, identity.conversation_id, kind])
        columns = list(SHAPES[table])
        cursor.execute(sql.SQL("SELECT {} FROM {} WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s FOR UPDATE").format(
            sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table)),
            (identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id))
        row = cursor.fetchone()
        if row is None:
            continue
        cursor.execute(sql.SQL("SELECT 1 FROM {} WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s").format(sql.Identifier(table)), identity.values())
        if cursor.fetchone() is not None:
            raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "selected viewer already has state; explicit reconciliation required")
        values = list(row)
        values[columns.index("actor_ref")] = identity.actor_ref
        cursor.execute(sql.SQL("INSERT INTO {}({}) VALUES ({})").format(sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, columns)), sql.SQL(",").join(sql.Placeholder() for _ in columns)), values)
    cursor.execute("INSERT INTO communication_client_viewer_adoptions(tenant_id,project_id,legacy_actor_ref,conversation_id,viewer_actor_ref,decision_ref) VALUES (%s,%s,%s,%s,%s,%s)",
        (identity.tenant_id, identity.project_id, legacy_actor_ref, identity.conversation_id, identity.actor_ref, decision_ref))

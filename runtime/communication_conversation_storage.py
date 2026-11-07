"""Serialized per-viewer conversation versions over actual message/private state.

Caller authorization remains with ProjectService. Registration stores only direct
pair references; sync is a getter fence and must not precede a private-cell write
in the same transaction. Writers use prepare_conversation_write, then write their
source cell; its AFTER trigger takes the counter lock in that source transaction.
No method commits, copies bodies, obtains an event stream lock or emits events.
"""
from __future__ import annotations

import json
import re

from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_storage import ClientStateIdentity
from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-conversation-view-versions", "communication_conversation_schema.sql", "1"
TABLE = "communication_conversation_versions"
FUNCTIONS = {"acs_conversation_address_hash": ("text", "i", True),
    "acs_conversation_identity_guard": ("", "v", False),
    "acs_conversation_refresh": ("text,text,text,text,text,boolean,boolean", "v", False),
    "acs_conversation_message_version": ("", "v", False),
    "acs_conversation_private_refresh": ("text,text,text,text", "v", False),
    "acs_conversation_private_version": ("", "v", False)}
TRIGGERS = {"acs_conversation_version_guard": (TABLE, 19, "acs_conversation_identity_guard"),
    "acs_conversation_messages": ("communication_messages", 5, "acs_conversation_message_version"),
    "acs_conversation_read_state": ("communication_client_read_state", 29, "acs_conversation_private_version"),
    "acs_conversation_preferences": ("communication_client_preferences", 29, "acs_conversation_private_version")}
SHAPE = {"tenant_id": ("text", True), "project_id": ("text", True), "conversation_id": ("text", True),
    "viewer_address": ("text", True), "peer_address": ("text", True), "viewer_hash": ("bytea", True), "peer_hash": ("bytea", True),
    "actor_ref": ("text", False), "message_count": ("bigint", True), "read_revision": ("bigint", True),
    "preferences_revision": ("bigint", True), "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True)}


def _shape(connection, checksum):
    if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
        raise SchemaAdoptionError(NAME, checksum, "missing conversation version projection")
    rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
        "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (TABLE,)).fetchall()
    if {name: (kind, required) for name, kind, required in rows} != SHAPE:
        raise SchemaAdoptionError(NAME, checksum, "damaged conversation projection columns")
    keys = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n),i.indisprimary "
        "FROM pg_index i WHERE i.indrelid=to_regclass(%s) AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive AND i.indpred IS NULL", (TABLE,)).fetchall()
    if (["tenant_id", "project_id", "viewer_hash", "peer_hash"], True) not in keys or (["tenant_id", "project_id", "conversation_id", "actor_ref"], False) not in keys:
        raise SchemaAdoptionError(NAME, checksum, "missing conversation view identity fences")
    generated = connection.execute("SELECT a.attname,a.attgenerated,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
        "JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=to_regclass(%s) "
        "AND a.attname IN ('viewer_hash','peer_hash') ORDER BY a.attname", (TABLE,)).fetchall()
    if generated != [("peer_hash", "s", "acs_conversation_address_hash(peer_address)"), ("viewer_hash", "s", "acs_conversation_address_hash(viewer_address)")]:
        raise SchemaAdoptionError(NAME, checksum, "damaged conversation address hashing")
    checks = connection.execute("SELECT conname FROM pg_constraint WHERE conrelid=to_regclass(%s) AND contype='c' AND convalidated", (TABLE,)).fetchall()
    if not {"conversation_version_identity", "conversation_version_nonnegative", "conversation_version_hashes"} <= {row[0] for row in checks}:
        raise SchemaAdoptionError(NAME, checksum, "missing conversation projection bounds")
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    bodies = {name: body.strip() for name, _args, body in re.findall(
        r"CREATE FUNCTION ([a-z_]+)\((.*?)\)\s+RETURNS\s+.*?\bAS \$\$(.*?)\$\$;", source, re.DOTALL)}
    for name, (arguments, volatility, strict) in FUNCTIONS.items():
        row = connection.execute("SELECT prosrc,prosecdef,provolatile,proisstrict FROM pg_proc WHERE oid=to_regprocedure(%s)", (name + "(" + arguments + ")",)).fetchone()
        if row is None or row[0].strip() != bodies[name] or row[1:] != (False, volatility, strict):
            raise SchemaAdoptionError(NAME, checksum, "damaged conversation projection function")
    for trigger, (table, mask, function) in TRIGGERS.items():
        row = connection.execute("SELECT tgtype,tgenabled,tgfoid=to_regprocedure(%s),tgattr::text FROM pg_trigger "
            "WHERE tgname=%s AND tgrelid=to_regclass(%s) AND NOT tgisinternal", (function + "()", trigger, table)).fetchone()
        if row is None or row[0] != mask or row[1] not in {"O", "A"} or row[2:] != (True, ""):
            raise SchemaAdoptionError(NAME, checksum, "missing conversation source/fence trigger")
    foreign = connection.execute("SELECT confrelid=to_regclass('collaboration_projects'),convalidated,confdeltype,"
        "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),"
        "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
        "WHERE conrelid=to_regclass(%s) AND contype='f'", (TABLE,)).fetchall()
    if foreign != [(True, True, "c", ["tenant_id", "project_id"], ["tenant_id", "project_id"])]:
        raise SchemaAdoptionError(NAME, checksum, "missing conversation project scope")


def adopt_conversation_storage(connection):
    from runtime.communication_client_storage import verify_client_storage

    verify_client_storage(connection)
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-conversation-versions:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None:
            raise SchemaAdoptionError(NAME, checksum, "unversioned conversation projection")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit conversation projection migration required")
    _shape(connection, checksum)


def verify_conversation_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "conversation projection adoption required")
    _shape(connection, checksum)


def _pair(tenant, project, cid, viewer, peer):
    if any(type(value) is not str or not value or len(value) > 512 for value in (tenant, project, cid, viewer, peer)):
        raise ValueError("invalid conversation projection identity")
    if conversation_view_id(tenant, project, viewer, peer) != cid:
        raise ValueError("conversation reference differs from the actual address pair")


def _mapping(cursor, tenant, project, viewer, peer):
    cursor.execute("SELECT conversation_id,viewer_address,peer_address,actor_ref FROM communication_conversation_versions "
        "WHERE tenant_id=%s AND project_id=%s AND viewer_hash=acs_conversation_address_hash(%s) AND peer_hash=acs_conversation_address_hash(%s)",
        (tenant, project, viewer, peer))
    return cursor.fetchone()


def register_conversation_pair(cursor, tenant, project, cid, first_address, second_address):
    """Record both directions, never touch/update an existing counter row."""
    _pair(tenant, project, cid, first_address, second_address)
    if cursor.connection.autocommit:
        raise ValueError("conversation registration requires a caller transaction")
    for viewer, peer in sorted({(first_address, second_address), (second_address, first_address)}):
        row = _mapping(cursor, tenant, project, viewer, peer)
        if row is None:
            cursor.execute("INSERT INTO communication_conversation_versions(tenant_id,project_id,conversation_id,viewer_address,peer_address) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,project_id,viewer_hash,peer_hash) DO NOTHING", (tenant, project, cid, viewer, peer))
            row = _mapping(cursor, tenant, project, viewer, peer)
        if row is None or row[:3] != (cid, viewer, peer):
            raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "conversation address hash/identity conflict")


def _identity_pair(identity, viewer, peer):
    if not isinstance(identity, ClientStateIdentity):
        raise TypeError("an already-authorized scoped viewer identity is required")
    _pair(identity.tenant_id, identity.project_id, identity.conversation_id, viewer, peer)


def prepare_conversation_write(cursor, identity, viewer_address, peer_address):
    """Writer preparation only; AFTER source trigger acquires the counter lock."""
    _identity_pair(identity, viewer_address, peer_address)
    if cursor.connection.autocommit:
        raise ValueError("conversation write preparation requires a caller transaction")
    register_conversation_pair(cursor, identity.tenant_id, identity.project_id, identity.conversation_id, viewer_address, peer_address)
    row = _mapping(cursor, identity.tenant_id, identity.project_id, viewer_address, peer_address)
    if row[3] is not None and row[3] != identity.actor_ref:
        raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "conversation viewer actor changed")
    value = {"tenant_id": identity.tenant_id, "project_id": identity.project_id, "conversation_id": identity.conversation_id,
        "actor_ref": identity.actor_ref, "viewer_address": viewer_address, "peer_address": peer_address}
    cursor.execute("SELECT set_config('acs.conversation_write',%s,TRUE)", (json.dumps(value, ensure_ascii=False, sort_keys=True),))


def sync_conversation_view(cursor, identity, viewer_address, peer_address):
    """Getter fence. Retain its counter lock until all DTO source reads finish."""
    _identity_pair(identity, viewer_address, peer_address)
    if cursor.connection.autocommit:
        raise ValueError("conversation view synchronization requires a caller transaction")
    register_conversation_pair(cursor, identity.tenant_id, identity.project_id, identity.conversation_id, viewer_address, peer_address)
    try:
        cursor.execute("SELECT acs_conversation_refresh(%s,%s,%s,%s,%s,FALSE,FALSE)",
            (identity.tenant_id, identity.project_id, viewer_address, peer_address, identity.actor_ref))
        return cursor.fetchone()[0]
    except Exception as error:
        if getattr(error, "sqlstate", None) == "P0001" and "conversation_viewer_actor_conflict" in str(error):
            raise SchemaAdoptionError(NAME, schema_definition(FILE, VERSION)[1], "conversation viewer actor changed") from error
        raise

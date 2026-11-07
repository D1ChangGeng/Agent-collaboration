"""Bounded MCP hint publication frontiers, separate from message consumption."""
from __future__ import annotations

from collections.abc import Mapping

import anyio

from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError
from runtime.project_common import digest

NAME = "acs-communication-notification-frontiers"
FILE = "communication_notification_schema.sql"
TABLE = "communication_notification_frontiers"
KINDS = ("message", "notice")


def notification_owner(principal_ref, address):
    """Stable authenticated actor identity; two Slots sharing a principal differ."""
    return "actor:" + digest([principal_ref, address])


def adopt_notification_frontiers(connection):
    """Explicit operator transaction only; no request/startup DDL."""
    schema, checksum, equivalents = schema_definition(FILE)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-notification-frontiers:' || current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                             "WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    exists = connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None
    if row is not None and (row not in equivalents or not exists):
        raise SchemaAdoptionError(NAME, checksum, "explicit notification frontier migration required")
    if row is None and exists:
        raise SchemaAdoptionError(NAME, checksum, "unversioned notification frontier storage")
    connection.execute(schema)
    connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,'1',%s) "
        "ON CONFLICT(schema_name) DO UPDATE SET schema_checksum=EXCLUDED.schema_checksum", (NAME, checksum))


def verify_notification_frontiers(connection):
    _schema, checksum, equivalents = schema_definition(FILE)
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s",
                             (NAME,)).fetchone()
    exists = connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None
    if row not in equivalents or not exists:
        raise SchemaAdoptionError(NAME, checksum, "notification frontier adoption required")


def publication_boundary(keys):
    """At most two exact committed sequence references; never client timestamps."""
    if not isinstance(keys, (list, tuple)) or len(keys) > 2:
        raise ValueError("notification publication requires two bounded sequence references")
    result = dict.fromkeys(KINDS, 0)
    seen = set()
    for key in keys:
        if not isinstance(key, str) or len(key) > 32:
            raise ValueError("notification publication key is invalid")
        parts = key.split(":")
        if (len(parts) != 2 or parts[0] not in KINDS or parts[0] in seen
                or not parts[1].isascii() or not parts[1].isdecimal()
                or not 0 < int(parts[1]) <= 2**63 - 1):
            raise ValueError("notification publication key is invalid")
        seen.add(parts[0])
        result[parts[0]] = int(parts[1])
    return result


def due_publication_keys(keys, seen):
    current = publication_boundary(keys)
    seen = seen or {}
    if not isinstance(seen, Mapping) or any(type(seen.get(kind, 0)) is not int or seen.get(kind, 0) < 0 for kind in KINDS):
        raise ValueError("notification publication boundary is invalid")
    return [kind + ":" + str(current[kind]) for kind in KINDS if current[kind] > seen.get(kind, 0)]


def advance_publication_boundary(seen, keys):
    current = publication_boundary(keys)
    return {kind: max(current[kind], (seen or {}).get(kind, 0)) for kind in KINDS}


def stored_publication_boundary(cursor, identity):
    cursor.execute("SELECT message_sequence,notice_sequence FROM communication_notification_frontiers "
                   "WHERE tenant_id=%s AND project_id=%s AND owner_ref=%s AND session_ref=%s AND binding_revision=%s",
                   identity)
    row = cursor.fetchone()
    return {"message": row[0], "notice": row[1]} if row else dict.fromkeys(KINDS, 0)


def record_publication_boundary(cursor, identity, keys):
    boundary = publication_boundary(keys)
    cursor.execute("INSERT INTO communication_notification_frontiers(tenant_id,project_id,owner_ref,session_ref,"
        "binding_revision,message_sequence,notice_sequence) VALUES (%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(tenant_id,project_id,owner_ref,session_ref,binding_revision) DO UPDATE SET "
        "message_sequence=GREATEST(communication_notification_frontiers.message_sequence,EXCLUDED.message_sequence),"
        "notice_sequence=GREATEST(communication_notification_frontiers.notice_sequence,EXCLUDED.notice_sequence),"
        "updated_at=clock_timestamp()", (*identity, boundary["message"], boundary["notice"]))


async def publish_wake_hint(projects, project_id, session_ref, connection_ref, credential,
                            keys, seen, publish):
    """Advance hint progress only after the actual transport accepted the hint."""
    due = due_publication_keys(keys, seen)
    if not due:
        return advance_publication_boundary(seen, ())
    authorized = await anyio.to_thread.run_sync(projects.authorize_wake_publication,
        project_id, session_ref, connection_ref, due, credential)
    if not authorized:
        raise RuntimeError("notification publication binding changed before send")
    await publish()
    acknowledged = await anyio.to_thread.run_sync(projects.acknowledge_wake_publication,
        project_id, session_ref, connection_ref, due, credential)
    if not acknowledged:
        raise RuntimeError("notification publication binding changed")
    return advance_publication_boundary(seen, due)

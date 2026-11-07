"""Durable wait-channel reservation/selection, never model consumption evidence."""
from __future__ import annotations

from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME = "acs-communication-wait-ingress"
FILE = "communication_wait_schema.sql"


def enabled(authority):
    return (getattr(authority, "_wait_ingress_recovery_enabled", False)
            or getattr(authority, "_wait_ingress_storage_available", False))


def adopt_wait_ingress(connection):
    schema, checksum, equivalents = schema_definition(FILE)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-wait-ingress:' || current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                             "WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    exists = connection.execute("SELECT to_regclass('communication_wait_ingress')").fetchone()[0] is not None
    if row is not None and (row not in equivalents or not exists):
        raise SchemaAdoptionError(NAME, checksum, "explicit wait-ingress migration required")
    if row is None and exists:
        raise SchemaAdoptionError(NAME, checksum, "unversioned wait-ingress storage")
    connection.execute(schema)
    connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,'1',%s) "
        "ON CONFLICT(schema_name) DO UPDATE SET schema_checksum=EXCLUDED.schema_checksum", (NAME, checksum))


def verify_wait_ingress(connection):
    _schema, checksum, equivalents = schema_definition(FILE)
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone()
    if row not in equivalents or not connection.execute("SELECT to_regclass('communication_wait_ingress')").fetchone()[0]:
        raise SchemaAdoptionError(NAME, checksum, "wait-ingress adoption required")


def reserve(cursor, tenant, project, message, recipient, requests, expiry):
    cursor.execute("INSERT INTO communication_wait_ingress(tenant_id,project_id,message_id,recipient,request_ids,state,expires_at) "
        "VALUES (%s,%s,%s,%s,%s,'reserved',%s)", (tenant, project, message, recipient, requests, expiry))
    cursor.execute("UPDATE delivery_messages SET state='retry_wait',next_attempt_at=%s "
        "WHERE tenant_id=%s AND message_id=%s", (expiry, tenant, message))


def select(cursor, tenant, project, message, recipient, requests, waiter):
    cursor.execute("INSERT INTO communication_wait_ingress(tenant_id,project_id,message_id,recipient,request_ids,state,waiter_ref,expires_at,selected_at) "
        "VALUES (%s,%s,%s,%s,%s,'selected',%s,clock_timestamp(),clock_timestamp()) "
        "ON CONFLICT(tenant_id,project_id,message_id) DO UPDATE SET state='selected',waiter_ref=EXCLUDED.waiter_ref,selected_at=clock_timestamp()",
        (tenant, project, message, recipient, requests, waiter))


def gate(cursor, tenant, project, message):
    """Caller holds the original message lock; no network I/O occurs here."""
    cursor.execute("SELECT recipient,request_ids,state FROM communication_wait_ingress "
        "WHERE tenant_id=%s AND project_id=%s AND message_id=%s FOR UPDATE", (tenant, project, message))
    row = cursor.fetchone()
    if row is None or row[2] != "reserved":
        return row is not None and row[2] == "selected"
    cursor.execute("SELECT MAX(expires_at) FROM communication_waits WHERE tenant_id=%s AND project_id=%s "
        "AND address=%s AND request_id=ANY(%s) AND expires_at>clock_timestamp()",
        (tenant, project, row[0], row[1]))
    expiry = cursor.fetchone()[0]
    if expiry is not None:
        cursor.execute("UPDATE communication_wait_ingress SET expires_at=%s WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                       (expiry, tenant, project, message))
        cursor.execute("UPDATE delivery_messages SET next_attempt_at=%s WHERE tenant_id=%s AND message_id=%s", (expiry, tenant, message))
        return True
    cursor.execute("SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
        "AND layer IN ('runtime_dispatched','runtime_acknowledged','response_received') LIMIT 1", (tenant, message))
    if cursor.fetchone():
        cursor.execute("UPDATE communication_wait_ingress SET state='released' WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                       (tenant, project, message))
        return False  # Never reset or erase possible Native effects.
    cursor.execute("UPDATE communication_wait_ingress SET state='released' WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                   (tenant, project, message))
    cursor.execute("UPDATE delivery_messages SET state='queued',next_attempt_at=clock_timestamp() "
        "WHERE tenant_id=%s AND message_id=%s AND state='retry_wait' AND attempts=0", (tenant, message))
    return False


def reclaim_wait_ingress(authority, *, limit=64):
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("invalid wait ingress cleanup bound")
    if not enabled(authority):
        return 0
    with authority._connect() as connection:
        candidates = connection.execute("SELECT project_id,message_id FROM communication_wait_ingress WHERE tenant_id=%s "
            "AND state='reserved' AND expires_at<=clock_timestamp() ORDER BY expires_at,message_id LIMIT %s",
            (authority.tenant_id, limit)).fetchall()
    count = 0
    for project, message in candidates:
        with authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           ("communication-order:" + authority.tenant_id + ":" + project,))
            cursor.execute("SELECT message_id FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                           (authority.tenant_id, message))
            if cursor.fetchone() is not None:
                gate(cursor, authority.tenant_id, project, message)
                count += 1
    return count

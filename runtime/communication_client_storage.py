"""Private client-state storage below the existing ProjectService authorization.

Every call requires a cursor and identity that the owning service has already
authorized, including conversation/message membership and attachments. Helpers
perform no authentication, Native input, read-consumption or transcript storage.
Call one write helper per transaction, or acquire resource identities in a fixed
order when composing writes. The caller owns commit/rollback and event intent.

Separate read/prefs/draft rows provide independent CAS revisions. Retry receipts
preserve original results without copying sent messages. Draft deletion retains
a tombstone revision so a stale first-write client cannot resurrect old content.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC

from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, RevisionConflict, SchemaAdoptionError

NAME = "acs-communication-client-storage"
FILE = "communication_client_schema.sql"
VERSION = "1"
MAX_DRAFT_BYTES = 262_144
MAX_REVISION = 2**63 - 2
IDENTITY_COLUMNS = ("tenant_id", "project_id", "actor_ref", "conversation_id")
SHAPES = {
    "communication_client_read_state": {
        "tenant_id": ("text", True), "project_id": ("text", True), "actor_ref": ("text", True),
        "conversation_id": ("text", True), "through_message_handle": ("text", False),
        "through_sequence": ("bigint", True), "unread_override": ("boolean", True),
        "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True),
    },
    "communication_client_preferences": {
        "tenant_id": ("text", True), "project_id": ("text", True), "actor_ref": ("text", True),
        "conversation_id": ("text", True), "archived": ("boolean", True), "muted": ("boolean", True),
        "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True),
    },
    "communication_client_drafts": {
        "tenant_id": ("text", True), "project_id": ("text", True), "actor_ref": ("text", True),
        "conversation_id": ("text", True), "content": ("text", True), "attachment_refs": ("text[]", True),
        "deleted": ("boolean", True), "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True),
    },
    "communication_client_write_keys": {
        "tenant_id": ("text", True), "project_id": ("text", True), "actor_ref": ("text", True),
        "operation_kind": ("text", True), "client_request_id": ("text", True),
        "canonical_hash": ("text", True), "result_json": ("jsonb", True),
        "created_at": ("timestamp with time zone", True),
    },
    "communication_client_cursor_key": {
        "singleton": ("boolean", True), "secret": ("bytea", True),
        "created_at": ("timestamp with time zone", True),
    },
    "communication_delivery_versions": {
        "tenant_id": ("text", True), "message_id": ("text", True),
        "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True),
    },
    "communication_contact_versions": {
        "tenant_id": ("text", True), "project_id": ("text", True),
        "revision": ("bigint", True), "updated_at": ("timestamp with time zone", True),
    },
}
PRIMARY_KEYS = {name: IDENTITY_COLUMNS for name in SHAPES}
PRIMARY_KEYS["communication_client_write_keys"] = ("tenant_id", "actor_ref", "operation_kind", "client_request_id")
PRIMARY_KEYS["communication_client_cursor_key"] = ("singleton",)
PRIMARY_KEYS["communication_delivery_versions"] = ("tenant_id", "message_id")
PRIMARY_KEYS["communication_contact_versions"] = ("tenant_id", "project_id")
TRIGGERS = {
    "acs_client_delivery_message_version": ("delivery_messages", 21,
        ["attempts", "binding_revision", "endpoint_id", "last_error", "receipt_high_water", "state"]),
    "acs_client_delivery_receipt_version": ("delivery_receipts", 5, []),
    "acs_client_delivery_reply_version": ("communication_replies", 5, []),
}
CONTACT_PROJECT_TRIGGERS = {
    "acs_client_contact_teams_version": "collaboration_teams",
    "acs_client_contact_members_version": "collaboration_team_members",
    "acs_client_contact_memberships_version": "collaboration_memberships",
    "acs_client_contact_supervisors_version": "communication_supervisors",
}
CONTACT_SLOT_TRIGGERS = {
    "acs_client_contact_endpoints_version": "delivery_endpoints",
    "acs_client_contact_slots_version": "agent_slots",
}
TRIGGERS.update({name: (table, 29, []) for name, table in (CONTACT_PROJECT_TRIGGERS | CONTACT_SLOT_TRIGGERS).items()})
TRIGGERS["acs_client_contact_projects_version"] = ("collaboration_projects", 5, [])
TRIGGER_FUNCTIONS = {name: "acs_client_contact_project_version" for name in CONTACT_PROJECT_TRIGGERS}
TRIGGER_FUNCTIONS.update({name: "acs_client_contact_slot_version" for name in CONTACT_SLOT_TRIGGERS})
TRIGGER_FUNCTIONS["acs_client_contact_projects_version"] = "acs_client_contact_project_version"


def _reference(value, name):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError(name + " must be a nonempty bounded opaque reference")
    return value


@dataclass(frozen=True, slots=True)
class ClientStateIdentity:
    tenant_id: str
    project_id: str
    actor_ref: str
    conversation_id: str

    def __post_init__(self):
        for name in IDENTITY_COLUMNS:
            _reference(getattr(self, name), name)

    def values(self):
        return tuple(getattr(self, name) for name in IDENTITY_COLUMNS)


def _shape(connection, checksum):
    for table, wanted in SHAPES.items():
        exists = connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
        if exists is None:
            raise SchemaAdoptionError(NAME, checksum, "missing client relation: " + table)
        actual = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in actual} != wanted:
            raise SchemaAdoptionError(NAME, checksum, "incomplete client relation: " + table)
        primary = connection.execute("SELECT array_agg(a.attname ORDER BY x.ordinality),"
            "bool_and(i.indisunique AND i.indisvalid AND i.indisready AND i.indislive) "
            "FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY x(attnum,ordinality) "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=x.attnum "
            "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary GROUP BY i.indexrelid", (table,)).fetchall()
        if len(primary) != 1 or tuple(primary[0][0]) != PRIMARY_KEYS[table] or primary[0][1] is not True:
            raise SchemaAdoptionError(NAME, checksum, "invalid client CAS/dedup key: " + table)
    for name, (table, events, columns) in TRIGGERS.items():
        row = connection.execute("SELECT t.tgfoid=to_regprocedure(%s),t.tgenabled,t.tgtype,"
            "ARRAY(SELECT a.attname FROM pg_attribute a WHERE a.attrelid=t.tgrelid AND a.attnum=ANY(t.tgattr) ORDER BY a.attname) "
            "FROM pg_trigger t WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal",
            (TRIGGER_FUNCTIONS.get(name, name) + "()", name, table)).fetchone()
        if row is None or row[0] is not True or row[1] not in {"O", "A"} or row[2] != events or list(row[3]) != columns:
            raise SchemaAdoptionError(NAME, checksum, "missing/incomplete client version trigger: " + name)
    for function in ("acs_client_delivery_version_tick(text,text)", "acs_client_contact_version_tick(text,text)"):
        if connection.execute("SELECT to_regprocedure(%s)", (function,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing client version materializer: " + function)
    missing = connection.execute("SELECT 1 FROM collaboration_projects p LEFT JOIN communication_contact_versions v "
        "USING(tenant_id,project_id) WHERE v.project_id IS NULL LIMIT 1").fetchone()
    if missing is not None:
        raise SchemaAdoptionError(NAME, checksum, "missing contact projection version")
    cursor_secret(connection)


def adopt_client_storage(connection):
    """Explicit operator transaction. Existing/missing key data is never reset."""
    schema, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-client-storage:' || current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                             "WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is not None:
        if row not in equivalents:
            raise SchemaAdoptionError(NAME, checksum, "explicit client storage migration required")
        _shape(connection, checksum)
        return
    present = connection.execute("SELECT name FROM unnest(%s::text[]) name WHERE to_regclass(name) IS NOT NULL LIMIT 1",
                                 (list(SHAPES),)).fetchone()
    if present is not None:
        raise SchemaAdoptionError(NAME, checksum, "unversioned client storage: " + present[0])
    connection.execute(schema)
    connection.execute("INSERT INTO communication_client_cursor_key(singleton,secret) VALUES (TRUE,%s)", (secrets.token_bytes(32),))
    connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)",
                       (NAME, VERSION, checksum))
    _shape(connection, checksum)


def verify_client_storage(connection):
    _schema, checksum, equivalents = schema_definition(FILE, VERSION)
    metadata = connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0]
    row = (connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s",
                              (NAME,)).fetchone() if metadata is not None else None)
    if row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "client storage adoption required")
    _shape(connection, checksum)


def cursor_secret(connection):
    """Private exact key read; never regenerate, derive or return it in a DTO."""
    rows = connection.execute("SELECT singleton,secret FROM communication_client_cursor_key").fetchall()
    if len(rows) != 1 or rows[0][0] is not True or len(bytes(rows[0][1])) != 32:
        raise SchemaAdoptionError(NAME, "32-byte durable cursor key", "cursor key is missing or invalid")
    return bytes(rows[0][1])


def read_delivery_version(cursor, tenant_id, message_id):
    cursor.execute("SELECT revision,updated_at FROM communication_delivery_versions WHERE tenant_id=%s AND message_id=%s",
                   (tenant_id, message_id))
    row = cursor.fetchone()
    if row is None:
        raise LookupError("delivery version projection has not been materialized")
    return row[0], row[1].astimezone(UTC).isoformat()


def read_contact_version(cursor, tenant_id, project_id):
    """Read-only version of the authorized project's entire Contact projection."""
    cursor.execute("SELECT revision FROM communication_contact_versions WHERE tenant_id=%s AND project_id=%s",
                   (tenant_id, project_id))
    row = cursor.fetchone()
    if row is None:
        raise LookupError("contact version projection has not been materialized")
    return row[0]


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _lock(cursor, namespace, values):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (namespace + ":" + _canonical(values),))


def _revision(value):
    if type(value) is not int or not 0 <= value <= MAX_REVISION:
        raise ValueError("expected revision must be a bounded nonnegative integer")


def _start(cursor, identity, kind, key, value, expected_revision):
    if not isinstance(identity, ClientStateIdentity):
        raise TypeError("an already-authorized ClientStateIdentity is required")
    _reference(key, "client_request_id")
    _revision(expected_revision)
    canonical = hashlib.sha256(_canonical({"identity": identity.values(), "kind": kind,
        "input": value, "expected_revision": expected_revision}).encode()).hexdigest()
    _lock(cursor, "acs-client-write", [identity.tenant_id, identity.actor_ref, kind, key])
    cursor.execute("SELECT canonical_hash,result_json FROM communication_client_write_keys "
        "WHERE tenant_id=%s AND actor_ref=%s AND operation_kind=%s AND client_request_id=%s",
        (identity.tenant_id, identity.actor_ref, kind, key))
    previous = cursor.fetchone()
    if previous is not None:
        if previous[0] != canonical:
            raise IdempotencyConflict(key)
        return canonical, previous[1]
    resource_kind = "draft" if kind.startswith("draft.") else kind
    _lock(cursor, "acs-client-state", [*identity.values(), resource_kind])
    return canonical, None


def _finish(cursor, identity, kind, key, canonical, result):
    cursor.execute("INSERT INTO communication_client_write_keys(tenant_id,project_id,actor_ref,operation_kind,client_request_id,canonical_hash,result_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)", (identity.tenant_id, identity.project_id, identity.actor_ref, kind, key, canonical, _canonical(result)))
    return result


def _expect(identity, expected, actual):
    if expected != actual:
        raise RevisionConflict(identity.conversation_id, expected, actual, field="If-Match",
            guidance="Read the current personal state and reconsider the edit; keep the original key for exact retries.")


def _read_state(cursor, identity):
    cursor.execute("SELECT through_message_handle,through_sequence,unread_override,revision FROM communication_client_read_state "
        "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", identity.values())
    row = cursor.fetchone()
    return row if row is not None else (None, 0, False, 0)


def read_read_state(cursor, identity):
    row = _read_state(cursor, identity)
    return {"conversation_id": identity.conversation_id, "through_message_handle": row[0],
            "unread_override": row[2], "revision": row[3]}


def write_read_state(cursor, identity, *, through_message_handle, through_sequence,
                     expected_revision, client_request_id, unread_override=None):
    _reference(through_message_handle, "through_message_handle")
    if type(through_sequence) is not int or not 1 <= through_sequence <= 2**63 - 1:
        raise ValueError("the authorized visible message sequence must be positive")
    if unread_override is not None and type(unread_override) is not bool:
        raise ValueError("manual unread override must be a boolean")
    value = {"through_message_handle": through_message_handle, "through_sequence": through_sequence,
             "unread_override": unread_override}
    canonical, previous = _start(cursor, identity, "read_state", client_request_id, value, expected_revision)
    if previous is not None:
        return previous
    old_handle, old_sequence, old_unread, revision = _read_state(cursor, identity)
    _expect(identity, expected_revision, revision)
    if through_sequence < old_sequence:
        through_sequence, through_message_handle = old_sequence, old_handle
    elif through_sequence == old_sequence and old_handle is not None and old_handle != through_message_handle:
        raise ValueError("one authorized conversation sequence cannot name different messages")
    unread = old_unread if unread_override is None else unread_override
    result = {"conversation_id": identity.conversation_id, "through_message_handle": through_message_handle,
              "unread_override": unread, "revision": revision + 1}
    cursor.execute("INSERT INTO communication_client_read_state(tenant_id,project_id,actor_ref,conversation_id,through_message_handle,through_sequence,unread_override,revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,project_id,actor_ref,conversation_id) DO UPDATE SET "
        "through_message_handle=EXCLUDED.through_message_handle,through_sequence=EXCLUDED.through_sequence,"
        "unread_override=EXCLUDED.unread_override,revision=EXCLUDED.revision,updated_at=clock_timestamp()",
        (*identity.values(), through_message_handle, through_sequence, unread, revision + 1))
    return _finish(cursor, identity, "read_state", client_request_id, canonical, result)


def read_preferences(cursor, identity):
    cursor.execute("SELECT archived,muted,revision FROM communication_client_preferences "
        "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", identity.values())
    row = cursor.fetchone() or (False, False, 0)
    return {"archived": row[0], "muted": row[1], "revision": row[2]}


def write_preferences(cursor, identity, changes, *, expected_revision, client_request_id):
    if (type(changes) is not dict or not changes or set(changes) - {"archived", "muted"}
            or any(type(value) is not bool for value in changes.values())):
        raise ValueError("preference changes contain only specified archived/muted booleans")
    canonical, previous = _start(cursor, identity, "preferences", client_request_id, changes, expected_revision)
    if previous is not None:
        return previous
    old = read_preferences(cursor, identity)
    _expect(identity, expected_revision, old["revision"])
    result = {**old, **changes, "revision": old["revision"] + 1}
    cursor.execute("INSERT INTO communication_client_preferences(tenant_id,project_id,actor_ref,conversation_id,archived,muted,revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,project_id,actor_ref,conversation_id) DO UPDATE SET "
        "archived=EXCLUDED.archived,muted=EXCLUDED.muted,revision=EXCLUDED.revision,updated_at=clock_timestamp()",
        (*identity.values(), result["archived"], result["muted"], result["revision"]))
    return _finish(cursor, identity, "preferences", client_request_id, canonical, result)


def read_draft(cursor, identity):
    cursor.execute("SELECT content,attachment_refs,revision,updated_at FROM communication_client_drafts "
        "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", identity.values())
    row = cursor.fetchone()
    if row is None:
        return {"content": "", "attachment_refs": [], "revision": 0, "updated_at": None}
    return {"content": row[0], "attachment_refs": row[1], "revision": row[2],
            "updated_at": row[3].astimezone(UTC).isoformat()}


def _draft(cursor, identity, content, attachment_refs, expected_revision, key, *, deleted, validate_attachments=None):
    if type(content) is not str or len(content.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ValueError("draft exceeds the configured 256KiB UTF-8 default")
    if type(attachment_refs) is not list or len(attachment_refs) > 8:
        raise ValueError("draft attachment references must be a bounded list")
    for reference in attachment_refs:
        _reference(reference, "attachment_ref")
    kind = "draft.delete" if deleted else "draft.write"
    value = {"content": content, "attachment_refs": attachment_refs}
    canonical, previous = _start(cursor, identity, kind, key, value, expected_revision)
    if previous is not None:
        return previous
    old = read_draft(cursor, identity)
    _expect(identity, expected_revision, old["revision"])
    if validate_attachments is not None:
        # Exact retries above retain their original private write receipt even
        # after an upload expires. Only a new CAS-accepted save revalidates refs.
        validate_attachments(cursor, attachment_refs)
    cursor.execute("INSERT INTO communication_client_drafts(tenant_id,project_id,actor_ref,conversation_id,content,attachment_refs,deleted,revision) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,project_id,actor_ref,conversation_id) DO UPDATE SET "
        "content=EXCLUDED.content,attachment_refs=EXCLUDED.attachment_refs,deleted=EXCLUDED.deleted,revision=EXCLUDED.revision,updated_at=clock_timestamp() "
        "RETURNING updated_at", (*identity.values(), content, attachment_refs, deleted, old["revision"] + 1))
    updated = cursor.fetchone()[0]
    result = {"content": content, "attachment_refs": list(attachment_refs), "revision": old["revision"] + 1,
              "updated_at": updated.astimezone(UTC).isoformat()}
    return _finish(cursor, identity, kind, key, canonical, result)


def write_draft(cursor, identity, content, attachment_refs, *, expected_revision, client_request_id, validate_attachments=None):
    """Save private text/refs, optionally checking refs through short SQL only.

    The authorized facade owns the callback. It runs after exact receipt replay
    and revision checks, inside the caller's state/receipt transaction.
    """
    if validate_attachments is not None and not callable(validate_attachments):
        raise TypeError("a trusted attachment validation callback is required")
    return _draft(cursor, identity, content, attachment_refs, expected_revision, client_request_id,
                  deleted=False, validate_attachments=validate_attachments)


def delete_draft(cursor, identity, *, expected_revision, client_request_id):
    return _draft(cursor, identity, "", [], expected_revision, client_request_id, deleted=True)

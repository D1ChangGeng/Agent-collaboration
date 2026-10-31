"""Explicit additive adoption and read-only validation of communication storage."""
from __future__ import annotations

import hashlib
from pathlib import Path

from runtime.errors import SchemaAdoptionError

CORE_NAME = "acs-communication-core"
CORE_VERSION = "2"
CORE_FILE = "communication_core_schema.sql"
CORE_RELATIONS = (
    "runtime_schema_metadata", "command_dedup", "authority_instances", "scopes", "agent_slots", "grants",
    "grant_delegations", "domain_events", "outbox", "operations", "inbox_messages",
    "enrolled_nodes", "enrolled_node_keys", "enrolled_node_bindings", "enrolled_runtimes",
    "enrolled_node_challenges", "enrolled_node_command_proofs", "enrollment_command_views",
    "delivery_endpoints", "delivery_messages", "delivery_attempts", "delivery_receipts",
    "authority_transport_keys", "deployment_connection_refs", "delivery_endpoint_registrations",
    "delivery_transport_admissions", "delivery_receiver_receipts", "owner_node_commands",
)
CRITICAL_INDEXES = (
    ("command_dedup_command_id", "command_dedup"),
    ("authority_instances_one_active", "authority_instances"),
    ("delivery_attempts_one_open", "delivery_attempts"),
    ("authority_transport_keys_one_active", "authority_transport_keys"),
    ("delivery_endpoint_registrations_one_active", "delivery_endpoint_registrations"),
    ("delivery_transport_one_active_dispatch", "delivery_transport_admissions"),
    ("delivery_transport_one_prepare", "delivery_transport_admissions"),
)
# Exact 1.13 source at f0e9b9f, including its owner extension, in LF/CRLF forms.
# Older and unversioned databases need an explicit, separately verified adoption.
LEGACY_CORE = {
    ("1.13", "2d8672c71b4cb3a4f7e9f0fc829261c5b6d57f97777c445f79d85b493b0fa259"),
    ("1.13", "faf4b7edd70228be14d77cf9d176077fc349746fad2d4b6436eab6490e9762fe"),
}
# The released candidate's communication core, before task-free signed
# admissions could retain their absent task revision. Adoption only relaxes
# that column; stored packets, signatures and fences remain unchanged.
PREVIOUS_CORE = {
    ("1", "42d78b9fdae5b9b98b62e594b94a4a2e71e39fffc29e3b357de85a5b56e721cf"),
    ("1", "6b97364357ed259e515eb22ee59bfa26ec62ed00237666ba174c3a72197163be"),
}


def schema_definition(filename, version="1"):
    raw = Path(__file__).with_name(filename).read_bytes()
    canonical = raw.replace(b"\r\n", b"\n")
    checksum = hashlib.sha256(canonical).hexdigest()
    equivalents = {(version, hashlib.sha256(data).hexdigest())
                   for data in (raw, canonical, canonical.replace(b"\n", b"\r\n"))}
    return canonical, checksum, equivalents


def _metadata(connection, name):
    return connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                              "WHERE schema_name=%s", (name,)).fetchone()


def missing_relation(connection, names):
    return connection.execute("SELECT name FROM unnest(%s::text[]) AS name "
        "WHERE to_regclass(name) IS NULL LIMIT 1", (list(names),)).fetchone()


def _require_fences(connection, checksum):
    problem = connection.execute("SELECT wanted.name FROM unnest(%s::text[],%s::text[]) AS wanted(name,table_name) "
        "LEFT JOIN pg_index i ON i.indexrelid=to_regclass(wanted.name) WHERE i.indexrelid IS NULL "
        "OR i.indrelid<>to_regclass(wanted.table_name) OR NOT (i.indisunique AND i.indisvalid AND i.indisready AND i.indislive) LIMIT 1",
        ([name for name, _table in CRITICAL_INDEXES], [table for _name, table in CRITICAL_INDEXES])).fetchone()
    if problem is not None:
        raise SchemaAdoptionError(CORE_NAME, checksum, "missing_or_invalid_fence:" + problem[0])


def _require_admission_shape(connection, checksum):
    column = connection.execute("SELECT attnotnull,atttypid='int8'::regtype FROM pg_attribute "
        "WHERE attrelid=to_regclass('delivery_transport_admissions') AND attname='accepted_revision' "
        "AND attnum>0 AND NOT attisdropped").fetchone()
    if column != (False, True):
        raise SchemaAdoptionError(CORE_NAME, checksum, "task_revision_column_requires_adoption")


def adopt_core(connection):
    """Operator transaction only. Preserve old rows, identities and schema record."""
    definition, checksum, equivalent = schema_definition(CORE_FILE, CORE_VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-core-schema:' || current_schema(),0))")
    has_metadata = connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0] is not None
    current = _metadata(connection, CORE_NAME) if has_metadata else None
    if current is not None:
        if current not in equivalent | PREVIOUS_CORE:
            raise SchemaAdoptionError(CORE_NAME, checksum, str(current))
        missing = missing_relation(connection, CORE_RELATIONS)
        if missing is not None:
            raise SchemaAdoptionError(CORE_NAME, checksum, "missing_relation:" + missing[0])
        _require_fences(connection, checksum)
    else:
        legacy = _metadata(connection, "acs-p1-runtime") if has_metadata else None
        if legacy is not None:
            if legacy not in LEGACY_CORE:
                raise SchemaAdoptionError(CORE_NAME, checksum, str(legacy))
            missing = missing_relation(connection, CORE_RELATIONS)
            if missing is not None:
                raise SchemaAdoptionError(CORE_NAME, checksum, "missing_legacy_relation:" + missing[0])
            _require_fences(connection, checksum)
        else:
            occupied = connection.execute("SELECT name FROM unnest(%s::text[]) AS name "
                "WHERE to_regclass(name) IS NOT NULL LIMIT 1", (list(CORE_RELATIONS[1:]),)).fetchone()
            if occupied is not None:
                raise SchemaAdoptionError(CORE_NAME, checksum, "unversioned_existing_storage")
    connection.execute(definition)
    _require_fences(connection, checksum)
    _require_admission_shape(connection, checksum)
    connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
        "VALUES (%s,%s,%s) ON CONFLICT(schema_name) DO UPDATE SET "
        "schema_version=EXCLUDED.schema_version,schema_checksum=EXCLUDED.schema_checksum",
        (CORE_NAME, CORE_VERSION, checksum))


def verify_core(connection):
    """No DDL, repair, initialization or legacy adoption on server startup."""
    _definition, checksum, equivalent = schema_definition(CORE_FILE, CORE_VERSION)
    current = _metadata(connection, CORE_NAME)
    if current not in equivalent:
        raise SchemaAdoptionError(CORE_NAME, checksum, str(current))
    missing = missing_relation(connection, CORE_RELATIONS)
    if missing is not None:
        raise SchemaAdoptionError(CORE_NAME, checksum, "missing_relation:" + missing[0])
    _require_fences(connection, checksum)
    _require_admission_shape(connection, checksum)

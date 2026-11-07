"""Immutable, bounded 300-second metadata snapshots below service authorization.

The caller supplies its current authorized viewer/auth/filter identity on every
read. This module cannot establish permission or capture a source consistency
boundary; the service owns its short RR transaction and event high water.

Budgets charge canonical metadata bytes plus a fixed row allowance. They bound
logical cache storage, not PostgreSQL filesystem accounting. Expired caches are
eligible for bounded deletion; Authority history and personal state are untouched.
All writes keep the caller's transaction. Concurrent RR writers may need a fresh
transaction after SerializationFailure; no failed save exposes a partial cache.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, timedelta

from runtime.client_contracts import ClientContracts
from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-communication-snapshots", "communication_snapshot_schema.sql", "1"
TABLES = ("communication_snapshot_scopes", "communication_snapshots", "communication_snapshot_items")
FAMILIES = {"contacts": "Contact", "conversations": "Conversation", "receivers": "Receiver"}
MAX_ITEMS, MAX_BYTES = 50_000, 64 * 1024 * 1024
_contracts = ClientContracts()
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_REF = re.compile(r"snapshot-[A-Za-z0-9_-]{32}\Z")
SHAPES = {
    TABLES[0]: {"tenant_id": ("text", True), "project_id": ("text", True), "generation": ("bigint", True)},
    TABLES[1]: {"snapshot_ref": ("text", True), "tenant_id": ("text", True), "project_id": ("text", True),
        "viewer_key": ("text", True), "auth_revision": ("text", True), "filter_digest": ("text", True),
        "high_water": ("bigint", True), "projection_json": ("jsonb", True), "header_digest": ("text", True),
        "contacts_count": ("integer", True), "conversations_count": ("integer", True), "receivers_count": ("integer", True),
        "total_items": ("integer", True), "total_bytes": ("bigint", True),
        "created_at": ("timestamp with time zone", True), "expires_at": ("timestamp with time zone", True)},
    TABLES[2]: {"tenant_id": ("text", True), "project_id": ("text", True), "snapshot_ref": ("text", True),
        "resource_family": ("text", True), "item_index": ("integer", True), "resource_json": ("jsonb", True),
        "resource_digest": ("text", True)},
}
PRIMARY_KEYS = {TABLES[0]: ["tenant_id", "project_id"], TABLES[1]: ["snapshot_ref"],
                TABLES[2]: ["snapshot_ref", "resource_family", "item_index"]}
CHECKS = {TABLES[1]: {"snapshot_reference_format", "snapshot_identity_bounds", "snapshot_hash_format",
    "snapshot_metadata_object", "snapshot_size_bounds", "snapshot_ttl_bounds"},
    TABLES[2]: {"snapshot_family_bounds", "snapshot_item_object", "snapshot_item_hash"}}


def _shape(connection, checksum):
    for table, wanted in SHAPES.items():
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing snapshot cache relation")
        rows = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in rows} != wanted:
            raise SchemaAdoptionError(NAME, checksum, "damaged snapshot cache columns")
        keys = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
            "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (table,)).fetchall()
        if keys != [(PRIMARY_KEYS[table],)]:
            raise SchemaAdoptionError(NAME, checksum, "damaged snapshot cache primary key")
        checked = {row[0] for row in connection.execute("SELECT conname FROM pg_constraint WHERE conrelid=to_regclass(%s) "
            "AND contype='c' AND convalidated", (table,)).fetchall()}
        if not CHECKS.get(table, set()) <= checked:
            raise SchemaAdoptionError(NAME, checksum, "missing snapshot cache bounds")
    for index, table, columns in (("communication_snapshots_expiry", TABLES[1], ["expires_at", "snapshot_ref"]),
                                 ("communication_snapshots_owner", TABLES[1], ["tenant_id", "project_id", "viewer_key"])):
        row = connection.execute("SELECT i.indisvalid AND i.indisready AND i.indislive,"
            "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
            "WHERE i.indexrelid=to_regclass(%s) AND i.indrelid=to_regclass(%s) AND i.indpred IS NULL AND i.indexprs IS NULL",
            (index, table)).fetchone()
        if row != (True, columns):
            raise SchemaAdoptionError(NAME, checksum, "missing snapshot cache lookup index")
    for table, target, columns in ((TABLES[0], "collaboration_projects", ["tenant_id", "project_id"]),
        (TABLES[1], TABLES[0], ["tenant_id", "project_id"]),
        (TABLES[2], TABLES[1], ["tenant_id", "project_id", "snapshot_ref"])):
        rows = connection.execute("SELECT c.confrelid=to_regclass(%s),c.convalidated,c.confdeltype,"
            "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),"
            "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
            "WHERE c.conrelid=to_regclass(%s) AND c.contype='f'", (target, table)).fetchall()
        if rows != [(True, True, "c", columns, columns)]:
            raise SchemaAdoptionError(NAME, checksum, "damaged snapshot cache namespace foreign key")
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    body = re.search(r"CREATE FUNCTION acs_communication_snapshot_immutable\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
                     source, re.DOTALL).group(1).strip()
    for trigger, table in (("acs_communication_snapshot_header_immutable", TABLES[1]),
                            ("acs_communication_snapshot_item_immutable", TABLES[2])):
        row = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure('acs_communication_snapshot_immutable()'),"
            "t.tgattr::text,p.prosrc,p.prosecdef,p.provolatile FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal", (trigger, table)).fetchone()
        if (row is None or row[0] != 19 or row[1] not in {"O", "A"} or row[2:4] != (True, "")
                or row[4].strip() != body or row[5:] != (False, "v")):
            raise SchemaAdoptionError(NAME, checksum, "damaged snapshot cache immutable guard")
    inconsistent = connection.execute("SELECT 1 FROM communication_snapshots h LEFT JOIN "
        "(SELECT snapshot_ref,count(*) total,count(*) FILTER(WHERE resource_family='contacts') contacts,"
        "count(*) FILTER(WHERE resource_family='conversations') conversations,count(*) FILTER(WHERE resource_family='receivers') receivers "
        "FROM communication_snapshot_items GROUP BY snapshot_ref) i USING(snapshot_ref) "
        "WHERE h.total_items<>COALESCE(i.total,0) OR h.contacts_count<>COALESCE(i.contacts,0) "
        "OR h.conversations_count<>COALESCE(i.conversations,0) OR h.receivers_count<>COALESCE(i.receivers,0) LIMIT 1").fetchone()
    if inconsistent is not None:
        raise SchemaAdoptionError(NAME, checksum, "incomplete immutable snapshot cache")
    if connection.execute("SELECT 1 FROM communication_snapshot_items GROUP BY snapshot_ref,resource_family "
        "HAVING min(item_index)<>0 OR max(item_index)<>count(*)-1 LIMIT 1").fetchone() is not None:
        raise SchemaAdoptionError(NAME, checksum, "incomplete snapshot page indexes")


def adopt_snapshot_storage(connection):
    """Explicit schema adoption only; never triggered by cache reads or writes."""
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-snapshots:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if any(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None for table in TABLES):
            raise SchemaAdoptionError(NAME, checksum, "unversioned snapshot cache storage")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit snapshot cache migration required")
    _shape(connection, checksum)


def verify_snapshot_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    metadata = connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0]
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() if metadata else None
    if row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "snapshot cache adoption required")
    _shape(connection, checksum)


class SnapshotExpired(ValueError):
    code = "snapshot_expired"


class SnapshotMismatch(ValueError):
    code = "snapshot_mismatch"


class SnapshotQuotaExceeded(ValueError):
    code = "snapshot_quota_exceeded"


class SnapshotCorrupt(RuntimeError):
    code = "snapshot_corrupt"


def _reference(value):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError("snapshot identity requires bounded explicit references")


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    tenant_id: str
    project_id: str
    viewer_key: str
    auth_revision: str
    filter_digest: str

    def __post_init__(self):
        for value in self.values()[:4]:
            _reference(value)
        if type(self.filter_digest) is not str or _HASH.fullmatch(self.filter_digest) is None:
            raise ValueError("snapshot filters require a canonical SHA-256 digest")

    def values(self):
        return self.tenant_id, self.project_id, self.viewer_key, self.auth_revision, self.filter_digest


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    max_items: int = 10_000
    max_bytes: int = 16 * 1024 * 1024
    max_snapshots_per_viewer: int = 8
    max_bytes_per_viewer: int = 32 * 1024 * 1024
    max_snapshots_per_project: int = 128
    max_bytes_per_project: int = 128 * 1024 * 1024

    def __post_init__(self):
        for name, maximum in (("max_items", MAX_ITEMS), ("max_bytes", MAX_BYTES),
            ("max_snapshots_per_viewer", 1000), ("max_bytes_per_viewer", 1024 * 1024 * 1024),
            ("max_snapshots_per_project", 1000), ("max_bytes_per_project", 1024 * 1024 * 1024)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid snapshot storage budget")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def snapshot_filter_digest(filters):
    if type(filters) is not dict:
        raise ValueError("snapshot filters must be an explicit JSON object")
    encoded = _canonical(filters).encode("utf-8")
    if len(encoded) > 8192:
        raise ValueError("snapshot filter identity is too large")
    return hashlib.sha256(encoded).hexdigest()


def _projection(value):
    if type(value) is not dict or set(value) != {"actor", "notice_count"}:
        raise ValueError("snapshot projection contains only actor and notice_count")
    if type(value["notice_count"]) is not int or not 0 <= value["notice_count"] <= 2**63 - 1:
        raise ValueError("invalid snapshot notice count")
    return {"actor": _contracts.validate("Actor", value["actor"]), "notice_count": value["notice_count"]}


def _materialize(projection, pages, limits):
    projection = _projection(projection)
    if type(pages) is not dict or set(pages) != set(FAMILIES):
        raise ValueError("snapshot requires the complete three metadata families")
    count = 0
    for family in FAMILIES:
        if type(pages[family]) is not list:
            raise ValueError("snapshot families must be fully materialized ordered lists")
        count += len(pages[family])
    if count > limits.max_items:
        raise SnapshotQuotaExceeded("snapshot metadata item budget exceeded")
    charged = len(_canonical(projection).encode("utf-8")) + 512
    rows, counts = [], {}
    for family, model in FAMILIES.items():
        counts[family] = len(pages[family])
        for index, value in enumerate(pages[family]):
            validated = _contracts.validate(model, value)
            encoded = _canonical(validated)
            charged += len(encoded.encode("utf-8")) + 256
            if charged > limits.max_bytes:
                raise SnapshotQuotaExceeded("snapshot metadata byte budget exceeded")
            rows.append((family, index, encoded, _digest(validated)))
    if charged > limits.max_bytes:
        raise SnapshotQuotaExceeded("snapshot metadata byte budget exceeded")
    return projection, rows, counts, charged


def _write_transaction(connection):
    if connection.autocommit:
        raise ValueError("snapshot writes require a caller-owned transaction")
    # Establish an outer transaction even for a fresh connection. The nested
    # transaction below is a savepoint, so helpers never commit the caller.
    connection.execute("SELECT 1")
    return connection.transaction()


def _scope_fence(cursor, tenant, project):
    cursor.execute("INSERT INTO communication_snapshot_scopes(tenant_id,project_id) VALUES (%s,%s) "
        "ON CONFLICT(tenant_id,project_id) DO UPDATE SET generation=communication_snapshot_scopes.generation+1", (tenant, project))


def _prune(cursor, tenant, project, limit):
    cursor.execute("SELECT snapshot_ref FROM communication_snapshots WHERE tenant_id=%s AND project_id=%s "
        "AND expires_at<=clock_timestamp() ORDER BY expires_at,snapshot_ref LIMIT %s FOR UPDATE SKIP LOCKED", (tenant, project, limit))
    selected = [row[0] for row in cursor.fetchall()]
    if selected:
        cursor.execute("DELETE FROM communication_snapshots WHERE snapshot_ref=ANY(%s)", (selected,))
    return len(selected)


def _header_hash(identity, ref, high_water, projection, counts, charged, created, expires):
    return _digest([identity.values(), ref, high_water, projection, counts, charged, created, expires])


def save_snapshot(cursor, identity, projection, pages, *, high_water, ttl_seconds=300, limits=None):
    """Validate all metadata before writes; any admission/insert failure rolls back."""
    if not isinstance(identity, SnapshotIdentity):
        raise TypeError("a current authorized SnapshotIdentity is required")
    limits = limits if limits is not None else SnapshotLimits()
    if not isinstance(limits, SnapshotLimits):
        raise TypeError("validated snapshot storage limits are required")
    if type(high_water) is not int or not 0 <= high_water <= 2**63 - 1:
        raise ValueError("invalid captured event high water")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
        raise ValueError("snapshot TTL must be between 1 and 300 seconds")
    projection, rows, counts, charged = _materialize(projection, pages, limits)
    with _write_transaction(cursor.connection):
        _scope_fence(cursor, identity.tenant_id, identity.project_id)
        _prune(cursor, identity.tenant_id, identity.project_id, limits.max_snapshots_per_project)
        cursor.execute("SELECT count(*),COALESCE(sum(total_bytes),0),count(*) FILTER(WHERE viewer_key=%s),"
            "COALESCE(sum(total_bytes) FILTER(WHERE viewer_key=%s),0) FROM communication_snapshots WHERE tenant_id=%s AND project_id=%s",
            (identity.viewer_key, identity.viewer_key, identity.tenant_id, identity.project_id))
        project_count, project_bytes, viewer_count, viewer_bytes = cursor.fetchone()
        if (project_count >= limits.max_snapshots_per_project or project_bytes + charged > limits.max_bytes_per_project
                or viewer_count >= limits.max_snapshots_per_viewer or viewer_bytes + charged > limits.max_bytes_per_viewer):
            raise SnapshotQuotaExceeded("snapshot cache storage budget exceeded")
        cursor.execute("SELECT clock_timestamp()")
        created = cursor.fetchone()[0].astimezone(UTC)
        expires = created + timedelta(seconds=ttl_seconds)
        ref = "snapshot-" + secrets.token_urlsafe(24)
        created_text, expires_text = created.isoformat(), expires.isoformat()
        header_hash = _header_hash(identity, ref, high_water, projection, counts, charged, created_text, expires_text)
        cursor.execute("INSERT INTO communication_snapshots(snapshot_ref,tenant_id,project_id,viewer_key,auth_revision,filter_digest,"
            "high_water,projection_json,header_digest,contacts_count,conversations_count,receivers_count,total_items,total_bytes,created_at,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ref, *identity.values(), high_water, _canonical(projection), header_hash, *counts.values(), len(rows), charged, created, expires))
        if rows:
            cursor.executemany("INSERT INTO communication_snapshot_items(tenant_id,project_id,snapshot_ref,resource_family,item_index,resource_json,resource_digest) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)", [(*identity.values()[:2], ref, *row) for row in rows])
    return {"snapshot_ref": ref, "created_at": created_text, "expires_at": expires_text, "high_water": high_water,
            "projection": projection, "counts": counts}


def read_snapshot(cursor, identity, snapshot_ref):
    if not isinstance(identity, SnapshotIdentity):
        raise TypeError("a current authorized SnapshotIdentity is required")
    if type(snapshot_ref) is not str or _REF.fullmatch(snapshot_ref) is None:
        raise SnapshotExpired("snapshot is unavailable; capture a fresh view")
    cursor.execute("SELECT tenant_id,project_id,viewer_key,auth_revision,filter_digest,high_water,projection_json,header_digest,"
        "contacts_count,conversations_count,receivers_count,total_bytes,created_at,expires_at,expires_at<=clock_timestamp() "
        "FROM communication_snapshots WHERE snapshot_ref=%s FOR SHARE", (snapshot_ref,))
    row = cursor.fetchone()
    if row is None:
        raise SnapshotExpired("snapshot is unavailable; capture a fresh view")
    if tuple(row[:5]) != identity.values():
        raise SnapshotMismatch("snapshot viewer, authorization or filters changed")
    if row[14]:
        raise SnapshotExpired("snapshot expired; capture a fresh view")
    created, expires = row[12].astimezone(UTC).isoformat(), row[13].astimezone(UTC).isoformat()
    counts = dict(zip(FAMILIES, row[8:11], strict=True))
    try:
        projection = _projection(row[6])
        expected = _header_hash(identity, snapshot_ref, row[5], projection, counts, row[11], created, expires)
    except (TypeError, ValueError, KeyError) as error:
        raise SnapshotCorrupt("snapshot metadata integrity failed") from error
    if expected != row[7]:
        raise SnapshotCorrupt("snapshot metadata integrity failed")
    return {"snapshot_ref": snapshot_ref, "created_at": created, "expires_at": expires, "high_water": row[5],
            "projection": projection, "counts": counts}


def read_snapshot_page(cursor, identity, snapshot_ref, resource_family, *, offset=0, limit=50):
    if resource_family not in FAMILIES or type(offset) is not int or not 0 <= offset <= MAX_ITEMS:
        raise ValueError("invalid snapshot resource family or offset")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("snapshot page limit must be between 1 and 100")
    meta = read_snapshot(cursor, identity, snapshot_ref)
    total = meta["counts"][resource_family]
    cursor.execute("SELECT item_index,resource_json,resource_digest FROM communication_snapshot_items "
        "WHERE snapshot_ref=%s AND resource_family=%s AND item_index>=%s AND item_index<%s ORDER BY item_index",
        (snapshot_ref, resource_family, offset, offset + limit))
    rows = cursor.fetchall()
    if len(rows) != min(limit, max(0, total - offset)):
        raise SnapshotCorrupt("snapshot metadata page is incomplete")
    items = []
    for wanted, (index, resource, expected_digest) in enumerate(rows, offset):
        try:
            validated = _contracts.validate(FAMILIES[resource_family], resource)
        except (TypeError, ValueError) as error:
            raise SnapshotCorrupt("snapshot metadata page integrity failed") from error
        if index != wanted or _digest(validated) != expected_digest:
            raise SnapshotCorrupt("snapshot metadata page integrity failed")
        items.append(validated)
    next_offset = offset + len(items)
    return {"snapshot_ref": snapshot_ref, "items": items, "total": total,
            "next_offset": next_offset if next_offset < total else None}


def prune_snapshot_storage(connection, *, tenant_id=None, project_id=None, limit=100):
    """Bounded cache-only cleanup; caller owns commit/rollback and scheduling."""
    if project_id is not None and tenant_id is None:
        raise ValueError("project cleanup requires its tenant namespace")
    for value in (tenant_id, project_id):
        if value is not None:
            _reference(value)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("snapshot cleanup limit must be between 1 and 1000")
    removed = 0
    with _write_transaction(connection), connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT tenant_id,project_id FROM communication_snapshots WHERE expires_at<=clock_timestamp() "
            "AND (%s::text IS NULL OR tenant_id=%s) AND (%s::text IS NULL OR project_id=%s) ORDER BY tenant_id,project_id LIMIT %s",
            (tenant_id, tenant_id, project_id, project_id, limit))
        for tenant, project in cursor.fetchall():
            _scope_fence(cursor, tenant, project)
            removed += _prune(cursor, tenant, project, limit - removed)
            if removed == limit:
                break
    return removed

"""Binding-scoped receiver facts and semantic invalidations in caller transactions.

Callers must authorize Runtime visibility and recheck the same actual endpoint
before writing. This store rechecks/fences that subject, grants no permission,
and performs no provider I/O. Caller actions and supplier revision are not shared
state. Full metadata refreshes advance our counter; renewed proof/timestamps alone
do not cause GET -> event -> GET loops. A pure cached read never repairs storage.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError
from runtime.project_common import canonical, digest, handle
from runtime.receiver_contract import (
    CapabilityScope,
    ReceiverSnapshot,
    unknown_capabilities,
    unknown_observations,
)

NAME, FILE, VERSION = "acs-receiver-observations", "communication_receiver_observation_schema.sql", "1"
TABLE = "communication_receiver_observations"
FIELDS = ("endpoint_id", "agent_slot_id", "scope_id", "machine_id", "node_id", "revision",
          "supports_invoke", "boot_incarnation", "expires_at")
COLUMNS = ("selection_json", "selection_digest", "snapshot_json", "snapshot_digest", "resource_revision", "semantic_digest", "capability_digest")
SHAPE = {"tenant_id": ("text", True), "project_id": ("text", True), "receiver_id": ("text", True), "receiver_key": ("bytea", True),
    "selection_json": ("jsonb", True), "selection_digest": ("text", True), "snapshot_json": ("jsonb", True),
    "snapshot_digest": ("text", True), "resource_revision": ("bigint", True), "semantic_digest": ("text", True),
    "capability_digest": ("text", True), "observed_at": ("timestamp with time zone", True)}
MAX_BYTES, MAX_REVISION = 1048576, 2**63 - 1


class ReceiverObservationCorrupt(RuntimeError):
    code = "receiver_observation_corrupt"


def _reference(value):
    if type(value) is not str or not value.strip() or not 1 <= len(value) <= 512:
        raise ValueError("receiver observation requires a bounded explicit reference")
    return value


def _selection(record):
    if type(record) is not dict or any(field not in record for field in FIELDS):
        raise ValueError("actual endpoint metadata is required")
    result = {field: record[field] for field in FIELDS}
    for field in ("endpoint_id", "agent_slot_id", "scope_id", "machine_id", "node_id", "boot_incarnation"):
        _reference(result[field])
    if type(result["revision"]) is not int or not 0 <= result["revision"] <= MAX_REVISION or type(result["supports_invoke"]) is not bool:
        raise ValueError("invalid actual endpoint revision or invocation metadata")
    expiry = result["expires_at"]
    if expiry is not None:
        expiry = datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry
        if not isinstance(expiry, datetime) or expiry.tzinfo is None or expiry.utcoffset() is None:
            raise ValueError("endpoint expiration must be an aware timestamp")
        result["expires_at"] = expiry.astimezone(UTC).isoformat()
    return result


def _subject(snapshot, project, selected):
    if (snapshot.receiver_id != selected["endpoint_id"] or snapshot.address != handle("collaborator", project, selected["agent_slot_id"])
            or snapshot.binding_epoch != selected["revision"] or snapshot.capability_scope.connection_epoch != selected["revision"]
            or snapshot.capability_scope.execution_host_ref != selected["machine_id"]):
        raise ValueError("receiver snapshot differs from its actual endpoint subject")


def _wire(snapshot):
    encoded = snapshot.model_dump_json() if isinstance(snapshot, ReceiverSnapshot) else json.dumps(snapshot, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("receiver observation metadata exceeds its byte budget")
    return ReceiverSnapshot.model_validate_json(encoded).model_copy(update={"allowed_actions": ()})


def current_receiver_observation(snapshot, now):
    """Refresh original scoped proof deadlines; grant no caller actions."""
    result = snapshot.current(now, scope=snapshot.capability_scope)
    if not snapshot.capability_scope.complete:
        # Already-unknown Core facts can carry a more precise binding/disabled
        # reason. Missing capability scope must not erase that honest reason.
        result = result.model_copy(update={"observations": tuple(
            original if original.knowledge == "unknown" else current
            for original, current in zip(snapshot.observations, result.observations, strict=True))})
    session = next((item for item in result.observations if item.axis == "session"), None)
    if session is None or session.knowledge != "observed":
        result = result.model_copy(update={"native_session_ref": None})
    return result.model_copy(update={"allowed_actions": ()})


def _digests(snapshot, selected):
    full = snapshot.model_dump(mode="json")
    full.pop("revision")
    full.pop("allowed_actions")
    semantic = json.loads(canonical(full))
    for item in semantic["observations"]:
        for field in ("observed_at", "expires_at", "evidence_ref"):
            item.pop(field)
    for item in semantic["capabilities"]:
        for field in ("valid_until", "evidence_ref"):
            item.pop(field)
        item["conditions"] = sorted(item["conditions"])
    semantic["capabilities"].sort(key=lambda item: item["name"])
    semantic["observations"].sort(key=lambda item: item["axis"])
    return digest([selected, full]), digest([selected, semantic]), digest([
        selected, semantic["capability_scope"], semantic["capabilities"]])


def _decode(row, project):
    try:
        if type(row[0]) is not dict or set(row[0]) != set(FIELDS) or type(row[2]) is not dict or row[2].get("allowed_actions") != []:
            raise ValueError("receiver observation contains non-shared data")
        selected = _selection(row[0])
        snapshot = _wire(row[2])
        _subject(snapshot, project, selected)
        if (type(row[4]) is not int or not 1 <= row[4] <= MAX_REVISION or snapshot.revision != row[4]
                or snapshot.allowed_actions or digest(selected) != row[1]
                or digest([selected, snapshot.model_dump(mode="json")]) != row[3]
                or _digests(snapshot, selected)[1:] != (row[5], row[6])):
            raise ValueError("receiver observation integrity differs")
        return selected, snapshot
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise ReceiverObservationCorrupt("receiver observation integrity is unavailable") from error


def _unknown(selected, project, revision, reason):
    return ReceiverSnapshot(receiver_id=selected["endpoint_id"], address=handle("collaborator", project, selected["agent_slot_id"]),
        binding_epoch=selected["revision"], revision=revision, native_session_ref=None,
        capability_scope=CapabilityScope(adapter_id="unverified", adapter_version="unknown", harness_kind="unknown", harness_version=None,
            execution_host_ref=selected["machine_id"], binary_digest=None, config_digest=None,
            connection_epoch=selected["revision"], provider_generation=None), capabilities=unknown_capabilities(),
        observations=unknown_observations(selected["revision"], None, reason), allowed_actions=())


def _live_selection(cursor, tenant, project, selected, *, lock):
    cursor.execute("SELECT e.endpoint_id,e.agent_slot_id,e.scope_id,e.machine_id,e.node_id,e.revision,e.supports_invoke,e.boot_incarnation,e.expires_at "
        "FROM delivery_endpoints e WHERE e.tenant_id=%s AND e.endpoint_id=%s AND e.status='active' "
        "AND EXISTS(SELECT 1 FROM collaboration_projects p WHERE p.tenant_id=e.tenant_id AND p.project_id=%s AND p.state='active' "
        "AND (p.scope_id=e.scope_id OR EXISTS(SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=p.tenant_id "
        "AND r.project_id=p.project_id AND r.scope_id=e.scope_id)))" + (" FOR SHARE OF e" if lock else ""),
        (tenant, selected["endpoint_id"], project))
    row = cursor.fetchone()
    return _selection(dict(zip(FIELDS, row, strict=True))) if row else None


def _checks(value):
    return re.sub(r"\s|[()]|::(?:text|bigint|jsonb)", "", value.removeprefix("CHECK"))


def _shape(connection, checksum):
    if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
        raise SchemaAdoptionError(NAME, checksum, "missing receiver observation relation")
    columns = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
        "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (TABLE,)).fetchall()
    if {name: (kind, required) for name, kind, required in columns} != SHAPE:
        raise SchemaAdoptionError(NAME, checksum, "damaged receiver observation columns")
    key = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (TABLE,)).fetchall()
    if key != [(["tenant_id", "project_id", "receiver_key"],)]:
        raise SchemaAdoptionError(NAME, checksum, "missing receiver observation counter identity")
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    generated = connection.execute("SELECT a.attgenerated,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
        "JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=to_regclass(%s) AND a.attname='receiver_key'", (TABLE,)).fetchone()
    function = connection.execute("SELECT prosrc,proisstrict,provolatile,prosecdef,prorettype='bytea'::regtype "
        "FROM pg_proc WHERE oid=to_regprocedure('acs_receiver_observation_key(text)')").fetchone()
    body = source.split("AS $$", 1)[1].split("$$;", 1)[0].strip()
    function = (function[0].strip(), *function[1:]) if function else None
    if generated != ("s", "acs_receiver_observation_key(receiver_id)") or function != (body, True, "i", False, True):
        raise SchemaAdoptionError(NAME, checksum, "damaged receiver observation physical key")
    expected = {name: _checks("CHECK(" + body + ")") for name, body in re.findall(r"CONSTRAINT ([a-z_]+) CHECK \((.*)\)(?:,|$)", source, re.MULTILINE)}
    actual = {name: _checks(body) for name, body in connection.execute("SELECT conname,pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE conrelid=to_regclass(%s) AND contype='c' AND convalidated", (TABLE,)).fetchall()}
    if actual != expected:
        raise SchemaAdoptionError(NAME, checksum, "damaged receiver observation checks")
    foreign = connection.execute("SELECT c.confrelid::regclass::text,c.confdeltype,c.confupdtype,"
        "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),"
        "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
        "ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
        "WHERE c.conrelid=to_regclass(%s) AND c.contype='f' AND c.convalidated ORDER BY 1", (TABLE,)).fetchall()
    if foreign != [("collaboration_projects", "a", "a", ["tenant_id", "project_id"], ["tenant_id", "project_id"]),
                   ("delivery_endpoints", "a", "a", ["tenant_id", "receiver_id"], ["tenant_id", "endpoint_id"])]:
        raise SchemaAdoptionError(NAME, checksum, "damaged receiver observation subject fences")
    for project, *row in connection.execute("SELECT project_id," + ",".join(COLUMNS) + " FROM " + TABLE).fetchall():
        try:
            _decode(row, project)
        except ReceiverObservationCorrupt as error:
            raise SchemaAdoptionError(NAME, checksum, "damaged receiver observation data") from error


def adopt_receiver_observation_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-receiver-observations:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is not None:
            raise SchemaAdoptionError(NAME, checksum, "unversioned receiver observation relation")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit receiver observation migration required")
    _shape(connection, checksum)


def verify_receiver_observation_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    metadata = connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0]
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() if metadata else None
    if row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "receiver observation adoption required")
    _shape(connection, checksum)


def _require_metadata(cursor):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    cursor.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,))
    if cursor.fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "receiver observation adoption required")


def _events_adopted(cursor):
    from runtime.communication_event_storage import NAME as EVENT_NAME
    from runtime.communication_event_storage import TABLES, verify_event_storage

    cursor.execute("SELECT name FROM unnest(%s::text[]) name WHERE to_regclass(name) IS NOT NULL", (list(TABLES),))
    present = cursor.fetchall()
    cursor.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (EVENT_NAME,))
    metadata = cursor.fetchone()
    if not present and metadata is None:
        return False
    verify_event_storage(cursor.connection)
    return True


def record_receiver_observation(cursor, tenant, project, record, snapshot):
    """Caller owns authorization and commit. This helper owns only its savepoint."""
    _reference(tenant)
    _reference(project)
    selected, received = _selection(record), _wire(snapshot)
    _subject(received, project, selected)
    if cursor.connection.autocommit:
        raise ValueError("receiver observations require a caller-owned transaction")
    _require_metadata(cursor)
    if _live_selection(cursor, tenant, project, selected, lock=True) != selected:
        raise ValueError("receiver observation selection is no longer current")
    with cursor.connection.transaction():
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s||':'||encode(acs_receiver_observation_key(%s),'hex'),0))",
                       (NAME + ":" + digest([tenant, project]), selected["endpoint_id"]))
        cursor.execute("SELECT " + ",".join(COLUMNS) + " FROM " + TABLE + " WHERE tenant_id=%s AND project_id=%s "
                       "AND receiver_key=acs_receiver_observation_key(%s) AND receiver_id=%s FOR UPDATE",
                       (tenant, project, selected["endpoint_id"], selected["endpoint_id"]))
        old = cursor.fetchone()
        if old is not None:
            _old_selection, previous = _decode(old, project)
        # Both resource fences may wait longer than a short Native proof's TTL.
        # Normalize only after serialization, without extending source dates.
        cursor.execute("SELECT clock_timestamp()")
        received = current_receiver_observation(received, cursor.fetchone()[0])
        full, semantic, capabilities = _digests(received, selected)
        if old is not None:
            if _digests(previous, _old_selection)[0] == full:
                return previous
            if previous.revision == MAX_REVISION:
                raise OverflowError("receiver observation resource revision is exhausted")
        result = received.model_copy(update={"revision": old[4] + 1 if old else 1, "allowed_actions": ()})
        events = _events_adopted(cursor) if old is None or (semantic, capabilities) != (old[5], old[6]) else False
        cursor.execute("INSERT INTO " + TABLE + "(tenant_id,project_id,receiver_id,selection_json,selection_digest,snapshot_json,snapshot_digest,"
            "resource_revision,semantic_digest,capability_digest,observed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()) "
            "ON CONFLICT(tenant_id,project_id,receiver_key) DO UPDATE SET selection_json=EXCLUDED.selection_json,selection_digest=EXCLUDED.selection_digest,"
            "snapshot_json=EXCLUDED.snapshot_json,snapshot_digest=EXCLUDED.snapshot_digest,resource_revision=EXCLUDED.resource_revision,"
            "semantic_digest=EXCLUDED.semantic_digest,capability_digest=EXCLUDED.capability_digest,observed_at=EXCLUDED.observed_at "
            "WHERE " + TABLE + ".receiver_id=EXCLUDED.receiver_id",
            (tenant, project, selected["endpoint_id"], canonical(selected), digest(selected), result.model_dump_json(),
             digest([selected, result.model_dump(mode="json")]), result.revision, semantic, capabilities))
        if cursor.rowcount != 1:
            raise ReceiverObservationCorrupt("receiver observation physical key collision")
        if events:
            from runtime.communication_event_storage import record_event_intent

            for kind, changed in (("receiver.observed", old is None or semantic != old[5]),
                                  ("capability.changed", old is None or capabilities != old[6])):
                if changed:
                    record_event_intent(cursor, tenant, project, source_key="receiver-observation:" + digest([selected["endpoint_id"], result.revision, kind]),
                        kind=kind, resource_ref=selected["endpoint_id"], resource_revision=result.revision,
                        audience_kind="receiver", scope_id=selected["scope_id"])
        return result


def read_receiver_observation(cursor, tenant, project, record, now):
    """Pure cache read; stale/corrupt evidence cannot supply a prior Native Session."""
    _reference(tenant)
    _reference(project)
    selected = _selection(record)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("receiver observation comparison requires an aware clock")
    _require_metadata(cursor)
    cursor.execute("SELECT " + ",".join(COLUMNS) + " FROM " + TABLE + " WHERE tenant_id=%s AND project_id=%s "
                   "AND receiver_key=acs_receiver_observation_key(%s) AND receiver_id=%s",
                   (tenant, project, selected["endpoint_id"], selected["endpoint_id"]))
    row = cursor.fetchone()
    revision = row[4] if row and type(row[4]) is int and row[4] >= 1 else 0
    if _live_selection(cursor, tenant, project, selected, lock=False) != selected:
        return _unknown(selected, project, revision, "receiver_binding_changed")
    if row is None:
        return _unknown(selected, project, 0, "receiver_observation_unmeasured")
    try:
        stored, snapshot = _decode(row, project)
    except ReceiverObservationCorrupt:
        return _unknown(selected, project, revision, "receiver_observation_corrupt")
    if stored != selected:
        return _unknown(selected, project, revision, "receiver_binding_changed")
    return current_receiver_observation(snapshot, now)

"""Authorized-caller Native linkage metadata, immutable history and exact receipts.

The facade supplies current Core authorization, trusted identity/namespace and a
registry proof collected outside SQL. These helpers grant no Host permission,
perform no Host I/O, and never follow a new Native session automatically. Reads
return recorded linkage metadata; current Host permission is a separate boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from psycopg.pq import TransactionStatus
from pydantic import Field

from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, NotFound, RevisionConflict, SchemaAdoptionError
from runtime.native_view_models import ExistingSessionProof
from runtime.project_common import canonical, digest
from runtime.receiver_contract import CAPABILITY_NAMES, Contract

NAME, FILE, VERSION = "acs-communication-native-links", "communication_native_link_schema.sql", "1"
TABLES = ("communication_native_links", "communication_native_link_history", "communication_native_link_requests")
KEYS = ("tenant_key", "project_key", "scope_key", "link_key")
MAX_REVISION, MAX_METADATA = 2**63 - 1, 262144
Reference = Annotated[str, Field(min_length=1, max_length=512)]
Revision = Annotated[int, Field(ge=0, le=MAX_REVISION)]
_VIEWER = re.compile(r"viewer-[a-f0-9]{64}\Z")


class NativeLinkWrite(Contract):
    """The nine public binding fields; caller/permission fields are forbidden."""

    address: Reference
    receiver_ref: Reference
    expected_binding_epoch: Revision
    provider_ref: Reference
    native_session_ref: Reference
    native_authority: Literal["orca", "harness"]
    expected_revision: Revision
    expected_host_ref: Reference
    expected_provider_generation: Reference


class NativeLink(Contract):
    link_id: Reference
    project_id: Reference
    address: Reference
    receiver_ref: Reference
    binding_epoch: Revision
    provider_ref: Reference
    native_session_ref: Reference
    native_authority: Literal["orca", "harness"]
    capabilities: tuple[Literal[*CAPABILITY_NAMES], ...] = Field(max_length=len(CAPABILITY_NAMES))
    revision: Annotated[int, Field(ge=1, le=MAX_REVISION)]
    host_ref: Reference
    provider_generation: Reference


class NativeLinkCorrupt(RuntimeError):
    code = "native_link_corrupt"


class NativeLinkProofRejected(ValueError):
    code = "native_link_proof_rejected"


class NativeLinkQuotaExceeded(ValueError):
    code = "native_link_quota_exceeded"


def _reference(value, maximum=512):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError("Native link requires a bounded explicit reference")
    return value


@dataclass(frozen=True, slots=True)
class NativeLinkIdentity:
    tenant_id: str
    project_id: str
    scope_id: str
    viewer_key: str
    authority_id: str
    authority_incarnation: str
    access_mode: Literal["owner", "shared"]

    def __post_init__(self):
        for value in (self.tenant_id, self.project_id, self.scope_id, self.authority_id, self.authority_incarnation):
            _reference(value)
        if type(self.viewer_key) is not str or _VIEWER.fullmatch(self.viewer_key) is None:
            raise ValueError("an actual stable viewer key is required")
        if self.access_mode not in {"owner", "shared"}:
            raise ValueError("an explicit server-owned access mode is required")

    def resource(self, link_id):
        return self.tenant_id, self.project_id, self.scope_id, _reference(link_id)


@dataclass(frozen=True, slots=True)
class NativeLinkLimits:
    links_per_scope: int = 1024
    history_per_link: int = 4096
    requests_per_viewer: int = 16384
    metadata_bytes: int = 65536

    def __post_init__(self):
        for field, maximum in (("links_per_scope", 1000000), ("history_per_link", 1000000),
                               ("requests_per_viewer", 10000000), ("metadata_bytes", MAX_METADATA)):
            if type(getattr(self, field)) is not int or not 1 <= getattr(self, field) <= maximum:
                raise ValueError("invalid Native link limit: " + field)


DEFAULT_LIMITS = NativeLinkLimits()


@dataclass(frozen=True, slots=True)
class NativeLinkPosition:
    link_key: bytes
    link_id: str

    def __post_init__(self):
        _reference(self.link_id)
        if type(self.link_key) is not bytes or self.link_key != hashlib.sha256(self.link_id.encode("utf-8")).digest():
            raise ValueError("Native link position must bind the exact full identifier")


def native_link_position(link_id):
    return NativeLinkPosition(hashlib.sha256(_reference(link_id).encode("utf-8")).digest(), link_id)


def _date(value):
    instant = datetime.fromisoformat(value) if type(value) is str else value
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Native link timestamps require an aware clock")
    return instant


def _transaction(cursor):
    if cursor.connection.autocommit and cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("Native link writes require a caller-owned transaction")
    cursor.execute("SELECT 1")
    return cursor.connection.transaction()


def _metadata(cursor):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    cursor.execute("SELECT to_regclass('runtime_schema_metadata')")
    if cursor.fetchone()[0] is None:
        raise SchemaAdoptionError(NAME, checksum, "Native link adoption required")
    cursor.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,))
    if cursor.fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "Native link adoption required")


def require_native_link_storage(cursor):
    """Bounded request guard; full shape/data audits belong to startup/adoption."""
    _metadata(cursor)


def _scope(cursor, identity):
    if type(identity) is not NativeLinkIdentity:
        raise TypeError("an authorized server NativeLinkIdentity is required")
    cursor.execute("SELECT 1 FROM scopes s JOIN collaboration_projects p ON p.tenant_id=s.tenant_id "
        "JOIN authority_instances a ON a.authority_id=%s AND a.authority_incarnation=%s "
        "WHERE s.tenant_id=%s AND s.scope_id=%s AND s.status='active' AND p.project_id=%s AND p.state='active' "
        "AND a.status='active' AND (p.scope_id=s.scope_id OR EXISTS(SELECT 1 FROM collaboration_routes r "
        "WHERE r.tenant_id=p.tenant_id AND r.project_id=p.project_id AND r.scope_id=s.scope_id AND r.state='active')) "
        "FOR SHARE OF s,p,a", (identity.authority_id, identity.authority_incarnation, identity.tenant_id,
                              identity.scope_id, identity.project_id))
    if cursor.fetchone() is None:
        raise NotFound("Native link scope", identity.scope_id)


def _where():
    return " AND ".join(key + "=acs_native_link_key(%s)" for key in KEYS)


def _row(cursor, identity, link_id, *, revision=None, lock=False):
    values = identity.resource(link_id)
    table = TABLES[0] if revision is None else TABLES[1]
    cursor.execute("SELECT to_jsonb(n) FROM " + table + " n WHERE " + _where() +
        (" AND revision=%s" if revision is not None else "") + (" FOR UPDATE" if lock else ""),
        (*values, *((revision,) if revision is not None else ())))
    found = cursor.fetchone()
    if found is None:
        return None
    row = found[0]
    if tuple(row[field] for field in ("tenant_id", "project_id", "scope_id", "link_id")) != values:
        raise NativeLinkCorrupt("Native link physical key collision")
    _integrity(row)
    if revision is None:
        cursor.execute("SELECT to_jsonb(n) FROM " + TABLES[1] + " n WHERE " + _where() + " AND revision=%s",
                       (*values, row["revision"]))
        history = cursor.fetchone()
        if history is None or history[0] != row:
            raise NativeLinkCorrupt("Native link current revision differs from immutable history")
    return row


def _write_row(cursor, identity, link_id):
    # HTTP and event resource identity is (project,link_id). Scope owns that
    # resource; a second authorized Scope cannot reuse the same public ID.
    cursor.execute("SELECT tenant_id,project_id,scope_id,link_id FROM " + TABLES[0] + " WHERE "
        "tenant_key=acs_native_link_key(%s) AND project_key=acs_native_link_key(%s) "
        "AND link_key=acs_native_link_key(%s) FOR UPDATE", (identity.tenant_id, identity.project_id, link_id))
    row = cursor.fetchone()
    if row is not None:
        if (row[0], row[1], row[3]) != (identity.tenant_id, identity.project_id, link_id):
            raise NativeLinkCorrupt("Native link project resource key collision")
        if row[2] != identity.scope_id:
            raise NotFound("Native link", link_id)
    return _row(cursor, identity, link_id, lock=True)


def _supported(proof):
    return tuple(sorted(capability.name for capability in proof.intrinsic_capabilities if capability.support == "supported"))


def _proof_wire(proof):
    if type(proof) is not ExistingSessionProof:
        raise NativeLinkProofRejected("a typed registry ExistingSessionProof is required")
    try:
        result = ExistingSessionProof.model_validate_json(proof.model_dump_json())
    except (TypeError, ValueError) as error:
        raise NativeLinkProofRejected("Native source proof integrity is unavailable") from error
    if result.state != "verified":
        raise NativeLinkProofRejected("Native source has not been verified")
    return result


def _subject(identity, body, proof):
    selected, binding = proof.selection, proof.selection.binding
    if ((selected.tenant_id, selected.project_id, selected.scope_id) !=
            (identity.tenant_id, identity.project_id, identity.scope_id)
            or (binding.authority_id, binding.authority_incarnation) != (identity.authority_id, identity.authority_incarnation)
            or (body.address, body.receiver_ref, body.expected_binding_epoch, body.provider_ref, body.native_session_ref,
                body.native_authority, body.expected_host_ref, body.expected_provider_generation) !=
               (binding.actor_address, binding.receiver_id, binding.binding_epoch, proof.provider_ref,
                proof.native_session_ref, proof.native_authority, proof.host_ref, proof.provider_generation)):
        raise NativeLinkProofRejected("Native proof differs from the authorized binding request")


def _integrity(row):
    try:
        link = NativeLink.model_validate_json(json.dumps(row["link_json"]))
        proof = _proof_wire(ExistingSessionProof.model_validate_json(json.dumps(row["proof_json"])))
        selected, binding = proof.selection, proof.selection.binding
        if ((row["tenant_id"], row["project_id"], row["scope_id"], row["address"], row["receiver_ref"]) !=
                (selected.tenant_id, selected.project_id, selected.scope_id, binding.actor_address, binding.receiver_id)
                or (link.link_id, link.project_id, link.address, link.receiver_ref, link.revision) !=
                   (row["link_id"], row["project_id"], row["address"], row["receiver_ref"], row["revision"])
                or (link.binding_epoch, link.provider_ref, link.native_session_ref, link.native_authority,
                    link.host_ref, link.provider_generation) !=
                   (binding.binding_epoch, proof.provider_ref, proof.native_session_ref, proof.native_authority,
                    proof.host_ref, proof.provider_generation)
                or digest(row["link_json"]) != row["link_digest"] or digest(row["proof_json"]) != row["proof_digest"]
                or _date(row["updated_at"]) < _date(row["created_at"])):
            raise ValueError("Native link stored subject differs")
        current = proof.current(_date(row["updated_at"]))
        if current.state != "verified" or link.capabilities != _supported(current):
            raise ValueError("Native link source was not current at its recorded commit")
        return link
    except (TypeError, ValueError, KeyError) as error:
        raise NativeLinkCorrupt("Native link metadata integrity is unavailable") from error


def _context(identity, namespace):
    _reference(namespace, 4096)
    return canonical([identity.tenant_id, identity.project_id, identity.viewer_key,
                      identity.authority_id, identity.authority_incarnation, namespace])


def _prior(cursor, identity, link_id, body, namespace):
    context = _context(identity, namespace)
    cursor.execute("SELECT to_jsonb(r) FROM " + TABLES[2] + " r WHERE request_key=acs_native_link_key(%s)", (context,))
    result = cursor.fetchone()
    if result is None:
        return None
    row = result[0]
    if row["request_context"] != context:
        raise NativeLinkCorrupt("Native link request physical key collision")
    if (row["scope_id"] != identity.scope_id or row["link_id"] != link_id
            or digest([link_id, body.model_dump(mode="json")]) != row["input_digest"]):
        raise IdempotencyConflict(namespace)
    _request_integrity(cursor, row)
    return row["result_json"]


def _request_integrity(cursor, row):
    try:
        identity = NativeLinkIdentity(row["tenant_id"], row["project_id"], row["scope_id"], row["viewer_key"],
            row["authority_id"], row["authority_incarnation"], "shared")
        body = NativeLinkWrite.model_validate_json(json.dumps(row["input_json"]))
        if (row["request_context"] != _context(identity, row["request_namespace"])
                or row["input_digest"] != digest([row["link_id"], body.model_dump(mode="json")])
                or row["result_digest"] != digest(row["result_json"])):
            raise ValueError("request hash differs")
        history = _row(cursor, identity, row["link_id"], revision=row["revision"])
        if history is None or history["link_json"] != row["result_json"]:
            raise ValueError("request result differs from original history")
    except (TypeError, ValueError, KeyError, NativeLinkCorrupt) as error:
        raise NativeLinkCorrupt("Native link request integrity is unavailable") from error


def _source_rows(cursor, identity, proof):
    selected, binding = proof.selection, proof.selection.binding
    cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR SHARE",
                   (identity.tenant_id, binding.receiver_id))
    endpoint = cursor.fetchone()
    if endpoint is None:
        raise NativeLinkProofRejected("Native source endpoint is unavailable")
    endpoint = endpoint[0]
    if ((endpoint["scope_id"], endpoint["agent_slot_id"], endpoint["revision"], endpoint["machine_id"],
         endpoint["node_id"], endpoint["boot_incarnation"], endpoint["status"]) !=
            (selected.scope_id, selected.agent_slot_id, binding.binding_epoch, proof.host_ref,
             selected.node_id, selected.boot_incarnation, "active")):
        raise NativeLinkProofRejected("Native source endpoint is no longer current")
    cursor.execute("SELECT status FROM agent_slots WHERE tenant_id=%s AND agent_slot_id=%s AND scope_id=%s FOR SHARE",
                   (identity.tenant_id, selected.agent_slot_id, selected.scope_id))
    if cursor.fetchone() != ("active",):
        raise NativeLinkProofRejected("Native source Slot is no longer active")
    deadlines = [_date(endpoint["expires_at"])]
    cursor.execute("SELECT to_jsonb(n) FROM enrolled_nodes n WHERE tenant_id=%s AND node_id=%s FOR SHARE",
                   (identity.tenant_id, selected.node_id))
    node = cursor.fetchone()
    if node is None:
        if selected.node_binding_revision is not None or selected.runtime_id is not None:
            raise NativeLinkProofRejected("claimed Native enrollment is unavailable")
        return deadlines
    node = node[0]
    if ((node["status"], node["scope_id"], node["agent_slot_id"], node["authority_id"], node["authority_incarnation"]) !=
            ("active", selected.scope_id, selected.agent_slot_id, identity.authority_id, identity.authority_incarnation)
            or selected.node_binding_revision is not None and node["current_binding_revision"] != selected.node_binding_revision):
        raise NativeLinkProofRejected("Native Node enrollment changed")
    cursor.execute("SELECT to_jsonb(b),k.status FROM enrolled_node_bindings b JOIN enrolled_node_keys k USING(key_id) "
        "WHERE b.tenant_id=%s AND b.node_id=%s AND b.binding_revision=%s FOR SHARE OF b,k",
        (identity.tenant_id, selected.node_id, node["current_binding_revision"]))
    binding_row = cursor.fetchone()
    if binding_row is None or binding_row[1] != "active":
        raise NativeLinkProofRejected("Native Node key binding is unavailable")
    enrolled = binding_row[0]
    if (enrolled["status"], enrolled["machine_id"], enrolled["boot_incarnation"]) != ("active", proof.host_ref, selected.boot_incarnation):
        raise NativeLinkProofRejected("Native Node boot binding changed")
    deadlines.append(_date(enrolled["expires_at"]))
    if selected.runtime_id is not None:
        cursor.execute("SELECT to_jsonb(r) FROM enrolled_runtimes r WHERE tenant_id=%s AND runtime_id=%s FOR SHARE",
                       (identity.tenant_id, selected.runtime_id))
        runtime = cursor.fetchone()
        if runtime is None:
            raise NativeLinkProofRejected("Native Runtime enrollment is unavailable")
        runtime = runtime[0]
        if ((runtime["status"], runtime["node_id"], runtime["node_binding_revision"], runtime["node_boot_incarnation"],
             runtime["scope_id"], runtime["agent_slot_id"], runtime["authority_id"], runtime["authority_incarnation"]) !=
                ("active", selected.node_id, node["current_binding_revision"], selected.boot_incarnation,
                 selected.scope_id, selected.agent_slot_id, identity.authority_id, identity.authority_incarnation)
                or selected.runtime_binding_revision is not None and runtime["revision"] != selected.runtime_binding_revision):
            raise NativeLinkProofRejected("Native Runtime binding changed")
        deadlines.append(_date(runtime["expires_at"]))
    return deadlines


def _now(cursor):
    cursor.execute("SELECT clock_timestamp()")
    return cursor.fetchone()[0]


def _current(proof, identity, deadlines, now):
    result = proof.current(now)
    if result.state != "verified":
        raise NativeLinkProofRejected("Native source proof expired before commitment")
    if identity.access_mode != "owner" and any(expiry <= now for expiry in deadlines):
        raise NativeLinkProofRejected("Native source shared lease expired before commitment")
    return result


def _events_adopted(cursor):
    from runtime.communication_event_storage import NAME as EVENT_NAME
    from runtime.communication_event_storage import TABLES as EVENT_TABLES
    from runtime.communication_event_storage import verify_event_storage

    cursor.execute("SELECT name FROM unnest(%s::text[]) name WHERE to_regclass(name) IS NOT NULL", (list(EVENT_TABLES),))
    present = cursor.fetchall()
    cursor.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (EVENT_NAME,))
    if not present and cursor.fetchone() is None:
        return False
    verify_event_storage(cursor.connection)
    return True


def _quota(cursor, identity, old, limits):
    cursor.execute("SELECT count(*) FROM " + TABLES[0] + " WHERE tenant_key=acs_native_link_key(%s) "
        "AND project_key=acs_native_link_key(%s) AND scope_key=acs_native_link_key(%s)",
        (identity.tenant_id, identity.project_id, identity.scope_id))
    if old is None and cursor.fetchone()[0] >= limits.links_per_scope:
        raise NativeLinkQuotaExceeded("Native link Scope count limit reached")
    if old is not None and old["revision"] >= limits.history_per_link:
        raise NativeLinkQuotaExceeded("Native link immutable history limit reached")
    cursor.execute("SELECT count(*) FROM " + TABLES[2] + " WHERE tenant_id=%s AND project_id=%s AND viewer_key=%s",
                   (identity.tenant_id, identity.project_id, identity.viewer_key))
    if cursor.fetchone()[0] >= limits.requests_per_viewer:
        raise NativeLinkQuotaExceeded("Native link viewer receipt limit reached")


def native_link_request(cursor, identity, link_id, body, request_namespace):
    """Authorized original-outcome lookup before the facade contacts a Host.

    A miss creates nothing and grants no execution right. The later write repeats
    the lookup under the same request lock after its own current Core check.
    """
    body = NativeLinkWrite.model_validate_json(body.model_dump_json() if type(body) is NativeLinkWrite else json.dumps(body))
    _reference(link_id)
    with _transaction(cursor):
        _metadata(cursor)
        _scope(cursor, identity)
        context = _context(identity, request_namespace)
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (NAME + ":request:" + digest(context),))
        return _prior(cursor, identity, link_id, body, request_namespace)


def write_native_link(cursor, identity, link_id, body, proof, request_namespace, *, limits=DEFAULT_LIMITS):
    """No commit/I/O. Caller authorization precedes the original-result lookup."""
    if type(limits) is not NativeLinkLimits:
        raise TypeError("typed NativeLinkLimits required")
    body = NativeLinkWrite.model_validate_json(body.model_dump_json() if type(body) is NativeLinkWrite else json.dumps(body))
    _reference(link_id)
    with _transaction(cursor):
        _metadata(cursor)
        _scope(cursor, identity)
        context = _context(identity, request_namespace)
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (NAME + ":request:" + digest(context),))
        prior = _prior(cursor, identity, link_id, body, request_namespace)
        if prior is not None:
            return prior
        proof = _proof_wire(proof)
        _subject(identity, body, proof)
        # Both Scope/link quotas and cross-Scope viewer receipts serialize. Lock
        # order is viewer -> Scope -> resource -> actual endpoint/enrollment.
        for category, values in (("viewer", [identity.tenant_id, identity.project_id, identity.viewer_key]),
                                 ("scope", [identity.tenant_id, identity.project_id, identity.scope_id]),
                                 ("resource", [identity.tenant_id, identity.project_id, link_id])):
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (NAME + ":" + category + ":" + digest(values),))
        old = _write_row(cursor, identity, link_id)
        actual_revision = old["revision"] if old else 0
        if body.expected_revision != actual_revision:
            raise RevisionConflict(link_id, body.expected_revision, actual_revision)
        if old is not None and old["address"] != body.address:
            raise NativeLinkProofRejected("a Native link's logical address and Scope are immutable")
        if actual_revision == MAX_REVISION:
            raise OverflowError("Native link revision exhausted")
        _quota(cursor, identity, old, limits)
        deadlines = _source_rows(cursor, identity, proof)
        events = _events_adopted(cursor)
        # SQL time is intentionally measured after every serialization/row wait.
        now = _now(cursor)
        proof = _current(proof, identity, deadlines, now)
        result = NativeLink(link_id=link_id, project_id=identity.project_id, address=body.address,
            receiver_ref=body.receiver_ref, binding_epoch=body.expected_binding_epoch, provider_ref=body.provider_ref,
            native_session_ref=body.native_session_ref, native_authority=body.native_authority,
            capabilities=_supported(proof), revision=actual_revision + 1, host_ref=body.expected_host_ref,
            provider_generation=body.expected_provider_generation).model_dump(mode="json")
        proof_json = proof.model_dump(mode="json")
        if any(len(canonical(value).encode("utf-8")) > limits.metadata_bytes
               for value in (proof_json, result, body.model_dump(mode="json"))):
            raise NativeLinkQuotaExceeded("Native link metadata byte limit reached")
        values = (*identity.resource(link_id), body.address, body.receiver_ref, result["revision"], canonical(result), digest(result),
                  canonical(proof_json), digest(proof_json), _date(old["created_at"]) if old else now, now)
        columns = "tenant_id,project_id,scope_id,link_id,address,receiver_ref,revision,link_json,link_digest,proof_json,proof_digest,created_at,updated_at"
        if old is None:
            cursor.execute("INSERT INTO " + TABLES[0] + "(" + columns + ") VALUES (" + ",".join(["%s"] * 13) + ")", values)
        else:
            cursor.execute("UPDATE " + TABLES[0] + " SET receiver_ref=%s,revision=%s,link_json=%s,link_digest=%s,proof_json=%s,"
                "proof_digest=%s,updated_at=%s WHERE " + _where() + " AND tenant_id=%s AND project_id=%s AND scope_id=%s AND link_id=%s",
                (body.receiver_ref, result["revision"], canonical(result), digest(result), canonical(proof_json), digest(proof_json), now,
                 *identity.resource(link_id), *identity.resource(link_id)))
            if cursor.rowcount != 1:
                raise NativeLinkCorrupt("Native link physical key collision")
        cursor.execute("INSERT INTO " + TABLES[1] + "(" + columns + ") VALUES (" + ",".join(["%s"] * 13) + ")", values)
        cursor.execute("INSERT INTO " + TABLES[2] + "(request_context,request_namespace,tenant_id,project_id,scope_id,link_id,"
            "viewer_key,authority_id,authority_incarnation,revision,input_json,input_digest,result_json,result_digest) "
            "VALUES (" + ",".join(["%s"] * 14) + ")", (context, request_namespace, *identity.resource(link_id), identity.viewer_key,
            identity.authority_id, identity.authority_incarnation, result["revision"], body.model_dump_json(),
            digest([link_id, body.model_dump(mode="json")]), canonical(result), digest(result)))
        if events:
            from runtime.communication_event_storage import record_event_intent

            record_event_intent(cursor, identity.tenant_id, identity.project_id,
                source_key="native-link:" + digest([*identity.resource(link_id), result["revision"]]),
                kind="native_link.changed", resource_ref=link_id, resource_revision=result["revision"],
                audience_kind="receiver", scope_id=identity.scope_id, payload={})
        final = _current(proof, identity, deadlines, _now(cursor))
        if final.intrinsic_capabilities != proof.intrinsic_capabilities:
            raise NativeLinkProofRejected("Native capability freshness changed before commitment")
        return result


def read_native_link(cursor, identity, link_id, *, revision=None):
    _metadata(cursor)
    _scope(cursor, identity)
    if revision is not None and (type(revision) is not int or not 1 <= revision <= MAX_REVISION):
        raise ValueError("Native link history revision must be positive")
    row = _row(cursor, identity, link_id, revision=revision)
    if row is None:
        raise NotFound("Native link", link_id)
    return row["link_json"]


def list_native_links(cursor, identity, *, limit=100, after=None):
    _metadata(cursor)
    _scope(cursor, identity)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Native link page limit must be between 1 and 100")
    if after is not None and type(after) is not NativeLinkPosition:
        raise TypeError("an exact typed NativeLinkPosition is required")
    cursor.execute("SELECT link_id FROM " + TABLES[0] + " WHERE tenant_key=acs_native_link_key(%s) "
        "AND project_key=acs_native_link_key(%s) AND scope_key=acs_native_link_key(%s)" +
        (" AND (link_key,link_id COLLATE \"C\")>(%s,%s::text COLLATE \"C\")" if after is not None else "") +
        " ORDER BY link_key,link_id COLLATE \"C\" LIMIT %s", (identity.tenant_id, identity.project_id, identity.scope_id,
        *((after.link_key, after.link_id) if after is not None else ()), limit))
    identifiers = [row[0] for row in cursor.fetchall()]
    return [read_native_link(cursor, identity, identifier) for identifier in identifiers]


_BASE_SHAPE = {**dict.fromkeys(("tenant_id", "project_id", "scope_id", "link_id", "address", "receiver_ref", "link_digest", "proof_digest"), ("text", True)),
    **dict.fromkeys(KEYS, ("bytea", True)), "revision": ("bigint", True), "link_json": ("jsonb", True), "proof_json": ("jsonb", True),
    "created_at": ("timestamp with time zone", True), "updated_at": ("timestamp with time zone", True)}
SHAPES = {TABLES[0]: _BASE_SHAPE, TABLES[1]: _BASE_SHAPE,
    TABLES[2]: {**dict.fromkeys(("request_context", "request_namespace", "tenant_id", "project_id", "scope_id", "link_id", "viewer_key", "authority_id", "authority_incarnation", "input_digest", "result_digest"), ("text", True)),
        **dict.fromkeys((*KEYS, "request_key"), ("bytea", True)), "revision": ("bigint", True), "input_json": ("jsonb", True),
        "result_json": ("jsonb", True), "created_at": ("timestamp with time zone", True)}}


def _checks(value):
    return re.sub(r"\s|[()]|::(?:text|bigint|jsonb)", "", value.removeprefix("CHECK"))


def _shape(connection, checksum):
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    for table in TABLES:
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing Native link relation")
        columns = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in columns} != SHAPES[table]:
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link columns")
        primary = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
            "WHERE i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (table,)).fetchall()
        expected_key = ["request_key"] if table == TABLES[2] else [*KEYS, *(("revision",) if table == TABLES[1] else ())]
        if primary != [(expected_key,)]:
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link physical identity")
        generated_columns = list(zip(KEYS, ("tenant_id", "project_id", "scope_id", "link_id"), strict=True))
        if table == TABLES[2]:
            generated_columns.append(("request_key", "request_context"))
        for column, field in generated_columns:
            generated = connection.execute("SELECT a.attgenerated,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
                "JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=to_regclass(%s) AND a.attname=%s", (table, column)).fetchone()
            if generated != ("s", "acs_native_link_key(" + field + ")"):
                raise SchemaAdoptionError(NAME, checksum, "damaged Native link hash column")
        declared = source.split("CREATE TABLE " + table + " (", 1)[1].split("\n);", 1)[0]
        expected = {name: _checks("CHECK(" + body + ")") for name, body in re.findall(r"CONSTRAINT ([a-z_]+) CHECK\((.*)\)(?:,|$)", declared, re.MULTILINE)}
        actual = {name: _checks(body) for name, body in connection.execute("SELECT conname,pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE conrelid=to_regclass(%s) AND contype='c' AND convalidated", (table,)).fetchall()}
        if actual != expected:
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link metadata constraints")
    unique = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i "
        "WHERE i.indrelid=to_regclass(%s) AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive "
        "AND i.indpred IS NULL", (TABLES[0],)).fetchall()
    if (["tenant_key", "project_key", "link_key"],) not in unique:
        raise SchemaAdoptionError(NAME, checksum, "missing project-wide Native link URI identity")
    functions = {"acs_native_link_key(text)": (source.split("AS $$", 1)[1].split("$$;", 1)[0].strip(), True, "i")}
    for function in ("acs_native_link_current_guard", "acs_native_link_history_guard"):
        body = source.split("CREATE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql AS $$", 1)[1].split("$$;", 1)[0].strip()
        functions[function + "()"] = body, False, "v"
    for function, wanted in functions.items():
        actual = connection.execute("SELECT prosrc,proisstrict,provolatile,prosecdef FROM pg_proc WHERE oid=to_regprocedure(%s)", (function,)).fetchone()
        if actual is None or (actual[0].strip(), *actual[1:]) != (*wanted, False):
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link key/immutability function")
    for table, trigger, function in ((TABLES[0], "acs_native_link_current_guard", "acs_native_link_current_guard"),
            (TABLES[1], "acs_native_link_history_guard", "acs_native_link_history_guard"),
            (TABLES[2], "acs_native_link_request_guard", "acs_native_link_history_guard")):
        actual = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure(%s),cardinality(t.tgattr::smallint[]) "
            "FROM pg_trigger t WHERE t.tgrelid=to_regclass(%s) AND t.tgname=%s AND NOT t.tgisinternal", (function + "()", table, trigger)).fetchone()
        if actual != (27, "O", True, 0):
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link immutability trigger")
    foreign = {TABLES[0]: [("collaboration_projects", ["tenant_id", "project_id"], ["tenant_id", "project_id"]),
                          ("scopes", ["scope_id"], ["scope_id"]), ("delivery_endpoints", ["tenant_id", "receiver_ref"], ["tenant_id", "endpoint_id"])],
        TABLES[1]: [(TABLES[0], list(KEYS), list(KEYS)), ("collaboration_projects", ["tenant_id", "project_id"], ["tenant_id", "project_id"]),
                    ("scopes", ["scope_id"], ["scope_id"]), ("delivery_endpoints", ["tenant_id", "receiver_ref"], ["tenant_id", "endpoint_id"])],
        TABLES[2]: [(TABLES[1], [*KEYS, "revision"], [*KEYS, "revision"]),
                    ("collaboration_projects", ["tenant_id", "project_id"], ["tenant_id", "project_id"])]}
    for table, wanted in foreign.items():
        actual = connection.execute("SELECT c.confrelid::regclass::text,ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n),ARRAY(SELECT a.attname FROM unnest(c.confkey) "
            "WITH ORDINALITY k(attnum,n) JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
            "WHERE c.conrelid=to_regclass(%s) AND c.contype='f' AND c.convalidated AND c.confdeltype='a' AND c.confupdtype='a'", (table,)).fetchall()
        if sorted(actual) != sorted(wanted):
            raise SchemaAdoptionError(NAME, checksum, "damaged Native link source foreign key")
    try:
        for (row,) in connection.execute("SELECT to_jsonb(n) FROM " + TABLES[1] + " n").fetchall():
            _integrity(row)
        for (row,) in connection.execute("SELECT to_jsonb(n) FROM " + TABLES[0] + " n").fetchall():
            _integrity(row)
            history = connection.execute("SELECT min(revision),max(revision),count(*) FROM " + TABLES[1] + " WHERE " + _where(),
                tuple(row[field] for field in ("tenant_id", "project_id", "scope_id", "link_id"))).fetchone()
            if history != (1, row["revision"], row["revision"]):
                raise NativeLinkCorrupt("Native link immutable history frontier differs")
            current = connection.execute("SELECT to_jsonb(n) FROM " + TABLES[1] + " n WHERE " + _where() + " AND revision=%s",
                (*tuple(row[field] for field in ("tenant_id", "project_id", "scope_id", "link_id")), row["revision"])).fetchone()
            if current != (row,):
                raise NativeLinkCorrupt("Native link current row differs from its immutable history")
        with connection.cursor() as cursor:
            for (row,) in connection.execute("SELECT to_jsonb(r) FROM " + TABLES[2] + " r").fetchall():
                _request_integrity(cursor, row)
    except (ValueError, TypeError, KeyError, NativeLinkCorrupt) as error:
        raise SchemaAdoptionError(NAME, checksum, "damaged Native link data/provenance") from error


def adopt_native_link_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    for table in ("runtime_schema_metadata", "collaboration_projects", "scopes", "delivery_endpoints", "authority_instances"):
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "Native link Core/project dependencies unavailable")
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-native-links:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if any(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None for table in TABLES):
            raise SchemaAdoptionError(NAME, checksum, "unversioned Native link storage")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit Native link migration required")
    _shape(connection, checksum)


def verify_native_link_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    metadata = connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0]
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() if metadata else None
    if row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "Native link adoption required")
    _shape(connection, checksum)

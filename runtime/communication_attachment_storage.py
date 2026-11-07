"""Private upload reservations/chunks below existing Runtime authorization.

The facade supplies the real viewer/address/Scope and request namespace, checks
current permissions, and closes SQL transactions before reading upload/network
or publishing to Scope CAS. This module never opens paths/URLs or invokes Native.
Ready publication accepts only the exact typed CAS reference after the caller's
separate content validator and CAS verification. It does not claim MIME sniffing.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4

from psycopg.pq import TransactionStatus

from runtime.client_contracts import ClientContracts
from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, NotFound, RevisionConflict, SchemaAdoptionError
from runtime.models import ArtifactRef
from runtime.project_common import canonical, digest

NAME, FILE, VERSION = "acs-communication-attachments", "communication_attachment_schema.sql", "1"
TABLES = ("communication_attachments", "communication_attachment_chunks", "communication_attachment_requests", "communication_message_attachments")
MAX_FILE = 256 * 1024 * 1024
_contracts = ClientContracts()
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_VIEWER = re.compile(r"viewer-[a-f0-9]{64}\Z")
_ID = re.compile(r"attachment-[a-f0-9]{32}\Z")
SHAPES = {
    TABLES[0]: {**dict.fromkeys(("attachment_id", "tenant_id", "project_id", "viewer_key", "owner_address", "scope_id", "name", "media_type",
        "declared_sha256", "declaration_digest", "state"), ("text", True)), "declared_bytes": ("bigint", True),
        "revision": ("bigint", True), "generation": ("bigint", True), "lease_token": ("text", False),
        "lease_expires_at": ("timestamp with time zone", False), "chunk_bytes": ("integer", True), "received_bytes": ("bigint", True),
        "artifact_json": ("jsonb", False), "artifact_digest": ("text", False), "pinned": ("boolean", True),
        "created_at": ("timestamp with time zone", True), "expires_at": ("timestamp with time zone", False)},
    TABLES[1]: {"attachment_id": ("text", True), "generation": ("bigint", True), "chunk_offset": ("bigint", True),
        "data": ("bytea", True), "data_hash": ("bytea", True), "resulting_revision": ("bigint", True)},
    TABLES[2]: {**dict.fromkeys(("tenant_id", "project_id", "viewer_key", "request_namespace", "operation_kind", "input_digest", "result_digest", "attachment_id"), ("text", True)),
        "request_hash": ("bytea", True), "result_json": ("jsonb", True), "created_at": ("timestamp with time zone", True)},
    TABLES[3]: {**dict.fromkeys(("tenant_id", "project_id", "message_id", "attachment_id"), ("text", True)), "position": ("integer", True)},
}


class AttachmentQuotaExceeded(ValueError):
    code = "attachment_quota_exceeded"


class AttachmentExpired(ValueError):
    code = "attachment_expired"


class AttachmentUploadConflict(ValueError):
    code = "attachment_upload_conflict"


class AttachmentCorrupt(RuntimeError):
    code = "attachment_corrupt"


def _reference(value, maximum=512):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError("attachment identity requires a bounded explicit reference")
    return value


@dataclass(frozen=True, slots=True)
class AttachmentIdentity:
    tenant_id: str
    project_id: str
    viewer_key: str
    scope_id: str
    owner_address: str

    def __post_init__(self):
        for value in (self.tenant_id, self.project_id, self.owner_address):
            _reference(value)
        _reference(self.scope_id, 256)
        if type(self.viewer_key) is not str or not _VIEWER.fullmatch(self.viewer_key):
            raise ValueError("an actual stable viewer identity is required")

    def values(self):
        return self.tenant_id, self.project_id, self.viewer_key, self.scope_id, self.owner_address


@dataclass(frozen=True, slots=True)
class AttachmentLimits:
    file_bytes: int = 20 * 1024 * 1024
    attachments_per_message: int = 8
    message_bytes: int = 50 * 1024 * 1024
    viewer_bytes: int = 100 * 1024 * 1024
    project_bytes: int = 1024 * 1024 * 1024
    reservation_ttl_seconds: int = 24 * 3600
    chunk_bytes: int = 64 * 1024
    upload_lease_seconds: int = 15 * 60

    def __post_init__(self):
        for name, maximum in (("file_bytes", MAX_FILE), ("attachments_per_message", 64), ("message_bytes", 1024**3),
            ("viewer_bytes", 8 * 1024**3), ("project_bytes", 64 * 1024**3), ("reservation_ttl_seconds", 7 * 86400),
            ("chunk_bytes", 1024**2), ("upload_lease_seconds", 86400)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise ValueError("invalid attachment limit: " + name)


@dataclass(frozen=True, slots=True)
class UploadLease:
    attachment_id: str
    generation: int
    token: str
    revision: int
    expires_at: str
    chunk_bytes: int

    def __post_init__(self):
        if (type(self.attachment_id) is not str or not _ID.fullmatch(self.attachment_id)
                or type(self.generation) is not int or self.generation < 1 or type(self.revision) is not int or self.revision < 1
                or type(self.token) is not str or re.fullmatch(r"upload-[A-Za-z0-9_-]{32}", self.token) is None
                or type(self.chunk_bytes) is not int or not 1 <= self.chunk_bytes <= 1048576):
            raise ValueError("invalid internal upload lease")
        instant = datetime.fromisoformat(self.expires_at)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("upload lease deadline must be aware")


@dataclass(frozen=True, slots=True)
class UploadedAttachment:
    attachment: dict
    lease: UploadLease
    data: bytes


def _transaction(cursor):
    if cursor.connection.autocommit and cursor.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("attachment writes require a caller-owned transaction")
    cursor.execute("SELECT 1")
    return cursor.connection.transaction()


def _scope(cursor, owner):
    if not isinstance(owner, AttachmentIdentity):
        raise TypeError("an authorized attachment identity is required")
    cursor.execute("SELECT 1 FROM scopes s JOIN collaboration_projects p ON p.tenant_id=s.tenant_id "
        "WHERE s.scope_id=%s AND s.tenant_id=%s AND s.status='active' AND p.project_id=%s AND p.state='active' "
        "AND (p.scope_id=s.scope_id OR EXISTS(SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=p.tenant_id "
        "AND r.project_id=p.project_id AND r.scope_id=s.scope_id)) FOR SHARE OF s",
        (owner.scope_id, owner.tenant_id, owner.project_id))
    if cursor.fetchone() is None:
        raise NotFound("attachment scope", owner.scope_id)


def _quota_lock(cursor, tenant, project):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (NAME + ":" + digest([tenant, project]),))


def _declaration(owner, row):
    return digest([owner.values(), {"name": row["name"], "media_type": row["media_type"], "bytes": row["declared_bytes"],
                                  "sha256": row["declared_sha256"]}, row["chunk_bytes"]])


def _artifact(row):
    try:
        artifact = ArtifactRef.model_validate_json(json.dumps(row["artifact_json"]))
        if (artifact.immutable is not True or artifact.scope_id != row["scope_id"] or artifact.sha256 != row["declared_sha256"]
                or artifact.size_bytes != row["declared_bytes"] or artifact.media_type != row["media_type"]
                or artifact.path != artifact.sha256[:2] + "/" + artifact.sha256 or digest(artifact.model_dump(mode="json")) != row["artifact_digest"]):
            raise ValueError("artifact subject differs")
        return artifact
    except (ValueError, TypeError) as error:
        raise AttachmentCorrupt("ready attachment artifact integrity is unavailable") from error


def _integrity(row):
    owner = AttachmentIdentity(row["tenant_id"], row["project_id"], row["viewer_key"], row["scope_id"], row["owner_address"])
    if _declaration(owner, row) != row["declaration_digest"]:
        raise AttachmentCorrupt("attachment declaration integrity is unavailable")
    _contracts.validate("AttachmentCreate", {"name": row["name"], "media_type": row["media_type"],
        "bytes": row["declared_bytes"], "sha256": row["declared_sha256"]})
    if (not _ID.fullmatch(row["attachment_id"]) or type(row["revision"]) is not int or row["revision"] < 1
            or not 0 <= row["received_bytes"] <= row["declared_bytes"] or not 1 <= row["chunk_bytes"] <= 1048576
            or row["state"] in {"uploaded", "ready"} and row["received_bytes"] != row["declared_bytes"]
            or row["state"] == "ready" and row["artifact_json"] is None
            or row["pinned"] and (row["state"] != "ready" or row["expires_at"] is not None)
            or not row["pinned"] and (row["expires_at"] is None or _date(row["expires_at"]) <= _date(row["created_at"]))):
        raise AttachmentCorrupt("attachment lifecycle integrity is unavailable")
    if row["artifact_json"] is not None:
        if row["state"] not in {"ready", "expired"}:
            raise AttachmentCorrupt("unpublished attachment contains a ready artifact")
        _artifact(row)
    return row


def _load(cursor, owner, attachment_id, *, lock=False):
    _scope(cursor, owner)
    if type(attachment_id) is not str or not _ID.fullmatch(attachment_id):
        raise NotFound("attachment", str(attachment_id))
    cursor.execute("SELECT to_jsonb(a) FROM communication_attachments a WHERE tenant_id=%s AND project_id=%s "
        "AND viewer_key=%s AND scope_id=%s AND owner_address=%s AND attachment_id=%s" + (" FOR UPDATE" if lock else ""),
        (*owner.values(), attachment_id))
    row = cursor.fetchone()
    if row is None:
        raise NotFound("attachment", attachment_id)
    return _integrity(row[0])


def _now(cursor):
    cursor.execute("SELECT clock_timestamp()")
    return cursor.fetchone()[0]


def _date(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _live(row, now):
    if row["state"] == "expired" or not row["pinned"] and _date(row["expires_at"]) <= now:
        raise AttachmentExpired("attachment reservation expired")


def _dto(row, now=None):
    state = row["state"]
    if now is not None and not row["pinned"] and _date(row["expires_at"]) <= now:
        state = "expired"
    return _contracts.validate("Attachment", {"attachment_id": row["attachment_id"], "project_id": row["project_id"],
        "name": row["name"], "media_type": row["media_type"], "bytes": row["declared_bytes"], "sha256": row["declared_sha256"],
        "state": state, "upload_path": "/api/communication/v1/projects/" + quote(row["project_id"], safe="") + "/attachments/" + row["attachment_id"] + "/content"
            if state in {"reserved", "uploaded"} else None,
        "expires_at": row["expires_at"], "revision": row["revision"]})


def _revision(row, expected):
    if type(expected) is not int or expected != row["revision"]:
        raise RevisionConflict(row["attachment_id"], expected, row["revision"])
    if row["revision"] >= 2**63 - 1:
        raise OverflowError("attachment revision exhausted")


def _lease(row):
    return UploadLease(row["attachment_id"], row["generation"], row["lease_token"], row["revision"], row["lease_expires_at"], row["chunk_bytes"])


def _fence(row, lease, now):
    _live(row, now)
    if (not isinstance(lease, UploadLease) or lease.attachment_id != row["attachment_id"] or lease.generation != row["generation"]
            or lease.token != row["lease_token"] or row["lease_token"] is None or _date(row["lease_expires_at"]) <= now):
        raise AttachmentUploadConflict("upload generation or lease is stale")


def _prior(cursor, owner, namespace, kind, body):
    _reference(namespace)
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (NAME + ":request:" + digest([owner.values()[:3], namespace]),))
    cursor.execute("SELECT request_namespace,operation_kind,input_digest,result_json,result_digest,attachment_id FROM communication_attachment_requests "
        "WHERE tenant_id=%s AND project_id=%s AND viewer_key=%s AND request_hash=acs_attachment_request_hash(%s) FOR UPDATE",
        (owner.tenant_id, owner.project_id, owner.viewer_key, namespace))
    row = cursor.fetchone()
    if row:
        if row[:3] != (namespace, kind, digest(body)):
            raise IdempotencyConflict(namespace)
        if digest(row[3]) != row[4]:
            raise AttachmentCorrupt("attachment request receipt integrity is unavailable")
        _load(cursor, owner, row[5])
        return row[3]
    return None


def _receipt(cursor, owner, namespace, kind, body, attachment_id, result):
    if type(result) is not dict or len(canonical(result).encode()) > 65536:
        raise ValueError("attachment receipt must contain bounded JSON metadata")
    cursor.execute("INSERT INTO communication_attachment_requests(tenant_id,project_id,viewer_key,request_namespace,operation_kind,input_digest,"
        "result_json,result_digest,attachment_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (owner.tenant_id, owner.project_id, owner.viewer_key, namespace, kind, digest(body), canonical(result), digest(result), attachment_id))


def attachment_request(cursor, owner, attachment_id, namespace, kind, canonical_body, prepare=None):
    """Capture a facade plan/result atomically. prepare(cursor) is short SQL only.

    The callback must not upload, read network data or publish CAS. A lookup miss
    never writes; an exact retry returns its original result after state advances.
    """
    if type(kind) is not str or re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", kind) is None:
        raise ValueError("invalid internal attachment request kind")
    if prepare is not None and not callable(prepare):
        raise TypeError("a trusted SQL callback is required")
    with _transaction(cursor):
        _load(cursor, owner, attachment_id)
        prior = _prior(cursor, owner, namespace, kind, canonical_body)
        if prior is not None or prepare is None:
            return prior
        result = prepare(cursor)
        _receipt(cursor, owner, namespace, kind, canonical_body, attachment_id, result)
        return result


def get_attachment(cursor, owner, attachment_id, *, lock=False):
    return _dto(_load(cursor, owner, attachment_id, lock=lock), _now(cursor))


def reserve_attachment(cursor, owner, declaration, request_namespace, *, limits=None):
    limits = limits or AttachmentLimits()
    declaration = _contracts.validate("AttachmentCreate", declaration)
    if (declaration["bytes"] > limits.file_bytes or len(declaration["media_type"]) > 256
            or any(character in declaration["name"] for character in "/\\:")
            or any(ord(character) < 32 for character in declaration["name"] + declaration["media_type"])):
        raise ValueError("invalid attachment declaration or file bound")
    body = [owner.values(), declaration]
    with _transaction(cursor):
        _scope(cursor, owner)
        _quota_lock(cursor, owner.tenant_id, owner.project_id)
        prior = _prior(cursor, owner, request_namespace, "reserve", body)
        if prior is not None:
            return prior
        cursor.execute("SELECT COALESCE(sum(declared_bytes),0),COALESCE(sum(declared_bytes) FILTER(WHERE viewer_key=%s),0) "
            "FROM communication_attachments WHERE tenant_id=%s AND project_id=%s AND NOT pinned AND state NOT IN ('expired','rejected')",
            (owner.viewer_key, owner.tenant_id, owner.project_id))
        project_bytes, viewer_bytes = cursor.fetchone()
        if project_bytes + declaration["bytes"] > limits.project_bytes or viewer_bytes + declaration["bytes"] > limits.viewer_bytes:
            raise AttachmentQuotaExceeded("unassociated attachment reservation quota exceeded")
        attachment_id = "attachment-" + uuid4().hex
        cursor.execute("INSERT INTO communication_attachments(attachment_id,tenant_id,project_id,viewer_key,scope_id,owner_address,name,media_type,"
            "declared_bytes,declared_sha256,declaration_digest,chunk_bytes,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+%s*interval '1 second') RETURNING to_jsonb(communication_attachments)",
            (attachment_id, *owner.values(), declaration["name"], declaration["media_type"], declaration["bytes"], declaration["sha256"],
             digest([owner.values(), declaration, limits.chunk_bytes]), limits.chunk_bytes, limits.reservation_ttl_seconds))
        result = _dto(cursor.fetchone()[0])
        _receipt(cursor, owner, request_namespace, "reserve", body, attachment_id, result)
        return result


def begin_attachment_upload(cursor, owner, attachment_id, *, expected_revision, request_namespace, restart=False, limits=None):
    limits = limits or AttachmentLimits()
    if type(restart) is not bool:
        raise ValueError("restart must be an explicit boolean")
    body = [attachment_id, expected_revision, restart]
    with _transaction(cursor):
        _scope(cursor, owner)
        prior = _prior(cursor, owner, request_namespace, "begin", body)
        if prior is not None:
            return UploadLease(**prior)
        row = _load(cursor, owner, attachment_id, lock=True)
        now = _now(cursor)
        _live(row, now)
        _revision(row, expected_revision)
        if row["state"] not in {"reserved", "uploaded"}:
            raise AttachmentUploadConflict("attachment cannot accept another upload")
        if (not restart and row["lease_token"] is not None and _date(row["lease_expires_at"]) > now):
            result = _lease(row)
        else:
            cursor.execute("DELETE FROM communication_attachment_chunks WHERE attachment_id=%s", (attachment_id,))
            cursor.execute("UPDATE communication_attachments SET state='reserved',revision=revision+1,generation=generation+1,received_bytes=0,"
                "lease_token=%s,lease_expires_at=LEAST(expires_at,clock_timestamp()+%s*interval '1 second') WHERE attachment_id=%s "
                "RETURNING to_jsonb(communication_attachments)", ("upload-" + secrets.token_urlsafe(24), limits.upload_lease_seconds, attachment_id))
            result = _lease(cursor.fetchone()[0])
        _receipt(cursor, owner, request_namespace, "begin", body, attachment_id, asdict(result))
        return result


def append_attachment_chunk(cursor, owner, attachment_id, lease, offset, data):
    if type(offset) is not int or offset < 0 or type(data) is not bytes or not data:
        raise ValueError("a nonempty exact chunk and byte offset are required")
    with _transaction(cursor):
        row = _load(cursor, owner, attachment_id, lock=True)
        _fence(row, lease, _now(cursor))
        if row["state"] not in {"reserved", "uploaded"}:
            raise AttachmentUploadConflict("immutable attachment cannot accept chunks")
        if offset + len(data) > row["declared_bytes"] or offset % row["chunk_bytes"] or len(data) != min(row["chunk_bytes"], row["declared_bytes"] - offset):
            raise AttachmentUploadConflict("chunk exceeds declaration or differs from deterministic chunk boundaries")
        if offset < row["received_bytes"]:
            cursor.execute("SELECT data,data_hash,resulting_revision FROM communication_attachment_chunks WHERE attachment_id=%s AND generation=%s AND chunk_offset=%s",
                           (attachment_id, lease.generation, offset))
            chunk = cursor.fetchone()
            if chunk is None or bytes(chunk[0]) != data or bytes(chunk[1]) != hashlib.sha256(data).digest():
                raise AttachmentUploadConflict("chunk replay differs from original bytes")
            return {"offset": offset, "next_offset": offset + len(data), "revision": chunk[2], "generation": lease.generation}
        if offset != row["received_bytes"] or row["state"] != "reserved":
            raise AttachmentUploadConflict("chunk is out of order")
        _revision(row, row["revision"])
        revision = row["revision"] + 1
        cursor.execute("INSERT INTO communication_attachment_chunks(attachment_id,generation,chunk_offset,data,resulting_revision) VALUES (%s,%s,%s,%s,%s)",
                       (attachment_id, lease.generation, offset, data, revision))
        cursor.execute("UPDATE communication_attachments SET received_bytes=%s,revision=%s WHERE attachment_id=%s", (offset + len(data), revision, attachment_id))
        return {"offset": offset, "next_offset": offset + len(data), "revision": revision, "generation": lease.generation}


def _bytes(cursor, row):
    cursor.execute("SELECT chunk_offset,data,data_hash FROM communication_attachment_chunks WHERE attachment_id=%s AND generation=%s ORDER BY chunk_offset",
                   (row["attachment_id"], row["generation"]))
    data, offset, checksum = bytearray(), 0, hashlib.sha256()
    for position, raw, proof in cursor.fetchall():
        chunk = bytes(raw)
        if position != offset or len(chunk) != min(row["chunk_bytes"], row["declared_bytes"] - offset) or hashlib.sha256(chunk).digest() != bytes(proof):
            raise AttachmentCorrupt("staged attachment chunk integrity is unavailable")
        offset += len(chunk)
        if offset > row["declared_bytes"]:
            raise AttachmentCorrupt("staged attachment exceeds declaration")
        checksum.update(chunk)
        data.extend(chunk)
    if offset != row["declared_bytes"] or offset != row["received_bytes"] or checksum.hexdigest() != row["declared_sha256"]:
        raise AttachmentUploadConflict("uploaded attachment size or SHA-256 differs from declaration")
    return bytes(data)


def complete_attachment_upload(cursor, owner, attachment_id, lease, request_namespace):
    body = [attachment_id, asdict(lease)]
    with _transaction(cursor):
        _scope(cursor, owner)
        prior = _prior(cursor, owner, request_namespace, "complete", body)
        if prior is not None:
            return prior
        row = _load(cursor, owner, attachment_id, lock=True)
        _fence(row, lease, _now(cursor))
        if row["state"] not in {"reserved", "uploaded"}:
            raise AttachmentUploadConflict("attachment cannot complete another upload")
        _bytes(cursor, row)
        _fence(row, lease, _now(cursor))
        if row["state"] == "reserved":
            _revision(row, row["revision"])
            cursor.execute("UPDATE communication_attachments SET state='uploaded',revision=revision+1 WHERE attachment_id=%s RETURNING to_jsonb(communication_attachments)", (attachment_id,))
            row = cursor.fetchone()[0]
        result = _dto(row)
        _receipt(cursor, owner, request_namespace, "complete", body, attachment_id, result)
        return result


def read_uploaded_attachment(cursor, owner, attachment_id, lease, *, expected_revision):
    row = _load(cursor, owner, attachment_id)
    _fence(row, lease, _now(cursor))
    _revision(row, expected_revision)
    if row["state"] != "uploaded":
        raise AttachmentUploadConflict("only a complete staged upload can publish to CAS")
    data = _bytes(cursor, row)
    _fence(row, lease, _now(cursor))
    return UploadedAttachment(_dto(row), _lease(row), data)


def uploaded_attachment_lease(cursor, owner, attachment_id):
    row = _load(cursor, owner, attachment_id)
    if row["state"] != "uploaded":
        raise AttachmentUploadConflict("attachment is not an authoritative uploaded resource")
    lease = _lease(row)
    _fence(row, lease, _now(cursor))
    return lease


def finish_attachment_ready(cursor, owner, attachment_id, lease, artifact, *, expected_revision, request_namespace):
    if not isinstance(artifact, ArtifactRef):
        raise TypeError("a complete verified typed ArtifactRef is required")
    artifact = ArtifactRef.model_validate(artifact.model_dump(), strict=True)
    body = [attachment_id, asdict(lease), artifact.model_dump(mode="json"), expected_revision]
    with _transaction(cursor):
        _scope(cursor, owner)
        prior = _prior(cursor, owner, request_namespace, "ready", body)
        if prior is not None:
            return prior
        row = _load(cursor, owner, attachment_id, lock=True)
        _fence(row, lease, _now(cursor))
        _revision(row, expected_revision)
        if row["state"] != "uploaded":
            raise AttachmentUploadConflict("only uploaded bytes can become ready")
        candidate = row | {"artifact_json": artifact.model_dump(mode="json"), "artifact_digest": digest(artifact.model_dump(mode="json"))}
        _artifact(candidate)
        cursor.execute("UPDATE communication_attachments SET state='ready',revision=revision+1,artifact_json=%s,artifact_digest=%s,lease_token=NULL,lease_expires_at=NULL "
            "WHERE attachment_id=%s RETURNING to_jsonb(communication_attachments)",
            (artifact.model_dump_json(), candidate["artifact_digest"], attachment_id))
        result = _dto(cursor.fetchone()[0])
        cursor.execute("DELETE FROM communication_attachment_chunks WHERE attachment_id=%s", (attachment_id,))
        _receipt(cursor, owner, request_namespace, "ready", body, attachment_id, result)
        return result


def owner_artifact(cursor, owner, attachment_id):
    row = _load(cursor, owner, attachment_id)
    _live(row, _now(cursor))
    if row["state"] != "ready":
        raise AttachmentUploadConflict("attachment is not ready")
    return _artifact(row)


def reject_attachment(cursor, owner, attachment_id, *, expected_revision, request_namespace):
    """Record a separately established validation rejection; never claim sniffing."""
    body = [attachment_id, expected_revision]
    with _transaction(cursor):
        _scope(cursor, owner)
        prior = _prior(cursor, owner, request_namespace, "reject", body)
        if prior is not None:
            return prior
        row = _load(cursor, owner, attachment_id, lock=True)
        _live(row, _now(cursor))
        _revision(row, expected_revision)
        if row["state"] not in {"reserved", "uploaded"} or row["pinned"]:
            raise AttachmentUploadConflict("accepted attachment cannot be rejected by an uploader")
        cursor.execute("UPDATE communication_attachments SET state='rejected',received_bytes=0,lease_token=NULL,lease_expires_at=NULL,"
            "revision=revision+1 WHERE attachment_id=%s RETURNING to_jsonb(communication_attachments)", (attachment_id,))
        result = _dto(cursor.fetchone()[0])
        cursor.execute("DELETE FROM communication_attachment_chunks WHERE attachment_id=%s", (attachment_id,))
        _receipt(cursor, owner, request_namespace, "reject", body, attachment_id, result)
        return result


def _ref(row):
    return _contracts.validate("AttachmentRef", {"attachment_id": row["attachment_id"], "name": row["name"],
        "media_type": row["media_type"], "bytes": row["declared_bytes"], "sha256": row["declared_sha256"]})


def prepare_message_attachments(cursor, owner, attachment_ids, *, limits=None):
    """Freeze ready metadata before Packet admission, retaining locks to commit.

    The caller must associate these exact ordered IDs inside the same actual
    message transaction. Quota precedes sorted attachment locks, as in cleanup.
    """
    limits = limits or AttachmentLimits()
    if (type(attachment_ids) is not list or len(attachment_ids) > limits.attachments_per_message
            or any(type(identifier) is not str for identifier in attachment_ids)
            or len(set(attachment_ids)) != len(attachment_ids)):
        raise ValueError("message attachment count or identities are invalid")
    with _transaction(cursor):
        _scope(cursor, owner)
        _quota_lock(cursor, owner.tenant_id, owner.project_id)
        rows = {identifier: _load(cursor, owner, identifier, lock=True) for identifier in sorted(attachment_ids)}
        now = _now(cursor)
        for row in rows.values():
            _live(row, now)
            if row["state"] != "ready":
                raise AttachmentUploadConflict("all message attachments must be ready")
            _artifact(row)
        if sum(row["declared_bytes"] for row in rows.values()) > limits.message_bytes:
            raise AttachmentQuotaExceeded("message attachment byte limit exceeded")
        return [_ref(rows[identifier]) for identifier in attachment_ids]


def associate_attachments(cursor, owner, message_id, attachment_ids, *, limits=None):
    limits = limits or AttachmentLimits()
    if (type(attachment_ids) is not list or len(attachment_ids) > limits.attachments_per_message or len(set(attachment_ids)) != len(attachment_ids)):
        raise ValueError("message attachment count or identities are invalid")
    with _transaction(cursor):
        _scope(cursor, owner)
        _quota_lock(cursor, owner.tenant_id, owner.project_id)
        cursor.execute("SELECT sender FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND message_id=%s FOR SHARE",
                       (owner.tenant_id, owner.project_id, message_id))
        message = cursor.fetchone()
        if message is None or message[0] != owner.owner_address:
            raise NotFound("message", message_id)
        cursor.execute("SELECT attachment_id FROM communication_message_attachments WHERE tenant_id=%s AND project_id=%s AND message_id=%s ORDER BY position",
                       (owner.tenant_id, owner.project_id, message_id))
        original = [row[0] for row in cursor.fetchall()]
        if original and original != attachment_ids:
            raise AttachmentUploadConflict("an accepted message association is immutable")
        rows = {identifier: _load(cursor, owner, identifier, lock=True) for identifier in sorted(attachment_ids)}
        now = _now(cursor)
        for row in rows.values():
            _live(row, now)
            if row["state"] != "ready":
                raise AttachmentUploadConflict("all message attachments must be ready")
            _artifact(row)
        if sum(row["declared_bytes"] for row in rows.values()) > limits.message_bytes:
            raise AttachmentQuotaExceeded("message attachment byte limit exceeded")
        if not original:
            for position, identifier in enumerate(attachment_ids):
                row = rows[identifier]
                if not row["pinned"]:
                    _revision(row, row["revision"])
                    cursor.execute("UPDATE communication_attachments SET pinned=TRUE,expires_at=NULL,revision=revision+1 WHERE attachment_id=%s", (identifier,))
                cursor.execute("INSERT INTO communication_message_attachments VALUES (%s,%s,%s,%s,%s)",
                               (owner.tenant_id, owner.project_id, message_id, identifier, position))
        return [_ref(rows[identifier]) for identifier in attachment_ids]


def message_attachment_artifact(cursor, tenant, project, caller_address, message_id, attachment_id):
    """Caller first checks current read_message grants; participant checks repeat."""
    cursor.execute("SELECT to_jsonb(a) FROM communication_message_attachments m JOIN communication_messages c USING(tenant_id,project_id,message_id) "
        "JOIN communication_attachments a USING(tenant_id,project_id,attachment_id) WHERE m.tenant_id=%s AND m.project_id=%s "
        "AND m.message_id=%s AND m.attachment_id=%s AND (c.sender=%s OR c.recipient=%s) AND a.pinned AND a.state='ready'",
        (tenant, project, message_id, attachment_id, caller_address, caller_address))
    found = cursor.fetchone()
    if found is None:
        raise NotFound("attachment", attachment_id)
    row = _integrity(found[0])
    return _ref(row), _artifact(row)


def expire_attachment_staging(connection, *, tenant_id=None, project_id=None, limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000 or project_id is not None and tenant_id is None:
        raise ValueError("invalid attachment expiration bound")
    with _transaction(connection.cursor()):
        candidates = connection.execute("SELECT DISTINCT tenant_id,project_id FROM communication_attachments WHERE NOT pinned AND state<>'expired' "
            "AND expires_at<=clock_timestamp() AND (%s::text IS NULL OR tenant_id=%s) AND (%s::text IS NULL OR project_id=%s) "
            "ORDER BY tenant_id,project_id LIMIT %s", (tenant_id, tenant_id, project_id, project_id, limit)).fetchall()
        removed = 0
        for tenant, project in candidates:
            _quota_lock(connection.cursor(), tenant, project)
            rows = connection.execute("SELECT attachment_id FROM communication_attachments WHERE tenant_id=%s AND project_id=%s AND NOT pinned AND state<>'expired' "
                "AND expires_at<=clock_timestamp() ORDER BY expires_at,attachment_id LIMIT %s FOR UPDATE SKIP LOCKED", (tenant, project, limit - removed)).fetchall()
            for (identifier,) in rows:
                connection.execute("DELETE FROM communication_attachment_chunks WHERE attachment_id=%s", (identifier,))
                connection.execute("UPDATE communication_attachments SET state='expired',revision=revision+1,lease_token=NULL,lease_expires_at=NULL WHERE attachment_id=%s", (identifier,))
                removed += 1
            if removed == limit:
                break
        return removed


def _shape(connection, checksum):
    expected = {TABLES[0]: ["attachment_id"], TABLES[1]: ["attachment_id", "generation", "chunk_offset"],
                TABLES[2]: ["tenant_id", "project_id", "viewer_key", "request_hash"], TABLES[3]: ["tenant_id", "project_id", "message_id", "attachment_id"]}
    for table, key in expected.items():
        if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
            raise SchemaAdoptionError(NAME, checksum, "missing attachment relation")
        columns = connection.execute("SELECT attname,format_type(atttypid,atttypmod),attnotnull FROM pg_attribute "
            "WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped", (table,)).fetchall()
        if {name: (kind, required) for name, kind, required in columns} != SHAPES[table]:
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment columns")
        primary = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i WHERE i.indrelid=to_regclass(%s) "
            "AND i.indisprimary AND i.indisvalid AND i.indisready AND i.indislive", (table,)).fetchall()
        if primary != [(key,)]:
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment identity fence")
    for table, wanted in ((TABLES[0], ["tenant_id", "project_id", "attachment_id"]), (TABLES[3], ["tenant_id", "project_id", "message_id", "position"])):
        unique = connection.execute("SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
            "ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_index i WHERE i.indrelid=to_regclass(%s) "
            "AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive AND i.indpred IS NULL", (table,)).fetchall()
        if (wanted,) not in unique:
            raise SchemaAdoptionError(NAME, checksum, "missing attachment unique source fence")
    source = schema_definition(FILE, VERSION)[0].decode("utf-8")
    for table in TABLES:
        declared = source.split("CREATE TABLE " + table + " (", 1)[1].split("\n);", 1)[0]
        expected_checks = sorted(_normalize_check(value) for value in _ddl_checks(declared))
        actual_checks = sorted(_normalize_check(row[0].removeprefix("CHECK")) for row in connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=to_regclass(%s) AND contype='c' AND convalidated", (table,)).fetchall())
        if expected_checks != actual_checks:
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment bounds: " + table + " " + repr((
                sorted(set(expected_checks) - set(actual_checks)), sorted(set(actual_checks) - set(expected_checks)))))
    foreign_expected = {TABLES[0]: [("collaboration_projects", ["tenant_id", "project_id"]), ("scopes", ["scope_id"])],
        TABLES[1]: [(TABLES[0], ["attachment_id"])], TABLES[2]: [("collaboration_projects", ["tenant_id", "project_id"]), (TABLES[0], ["attachment_id"])],
        TABLES[3]: [(TABLES[0], ["tenant_id", "project_id", "attachment_id"]), ("communication_messages", ["tenant_id", "project_id", "message_id"])]}
    for table, wanted in foreign_expected.items():
        actual = connection.execute("SELECT c.confrelid::regclass::text,ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.n) FROM pg_constraint c "
            "WHERE c.conrelid=to_regclass(%s) AND c.contype='f' AND c.convalidated AND c.confdeltype='a' ORDER BY 1,2", (table,)).fetchall()
        if sorted(actual) != sorted(wanted):
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment source/Scope foreign key")
    for table, column, expression in ((TABLES[1], "data_hash", "sha256(data)"), (TABLES[2], "request_hash", "acs_attachment_request_hash(request_namespace)")):
        generated = connection.execute("SELECT a.attgenerated,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_attrdef d "
            "ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=to_regclass(%s) AND a.attname=%s", (table, column)).fetchone()
        if generated != ("s", expression):
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment generated integrity key")
    request_function = connection.execute("SELECT prosrc,proisstrict,provolatile,prosecdef FROM pg_proc "
        "WHERE oid=to_regprocedure('acs_attachment_request_hash(text)')").fetchone()
    request_body = source.split("AS $$", 1)[1].split("$$;", 1)[0].strip()
    if request_function is None or (request_function[0].strip(), *request_function[1:]) != (request_body, True, "i", False):
        raise SchemaAdoptionError(NAME, checksum, "damaged attachment namespace hash")
    body = source.split("LANGUAGE plpgsql AS $$", 1)[1].split("$$;", 1)[0].strip()
    function = connection.execute("SELECT prosrc,prosecdef,provolatile FROM pg_proc WHERE oid=to_regprocedure('acs_attachment_immutable()')").fetchone()
    trigger = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure('acs_attachment_immutable()') FROM pg_trigger t "
        "WHERE t.tgrelid=to_regclass('communication_attachments') AND t.tgname='acs_attachment_immutable' AND NOT t.tgisinternal").fetchone()
    if function is None or (function[0].strip(), *function[1:]) != (body, False, "v") or trigger != (19, "O", True):
        raise SchemaAdoptionError(NAME, checksum, "damaged attachment immutability fence")
    for (row,) in connection.execute("SELECT to_jsonb(a) FROM communication_attachments a").fetchall():
        try:
            _integrity(row)
            if row["state"] == "uploaded":
                _bytes(connection.cursor(), row)
        except (ValueError, TypeError, AttachmentCorrupt) as error:
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment metadata") from error
    invalid_chunks = connection.execute("SELECT 1 FROM communication_attachment_chunks c JOIN communication_attachments a USING(attachment_id) "
        "WHERE c.generation<>a.generation OR a.state NOT IN ('reserved','uploaded') OR c.chunk_offset%a.chunk_bytes<>0 "
        "OR octet_length(c.data)<>LEAST(a.chunk_bytes,a.declared_bytes-c.chunk_offset) OR c.data_hash<>sha256(c.data) "
        "OR c.resulting_revision>a.revision LIMIT 1").fetchone()
    invalid_order = connection.execute("SELECT 1 FROM (SELECT chunk_offset,COALESCE(sum(octet_length(data)) OVER(PARTITION BY attachment_id,generation "
        "ORDER BY chunk_offset ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) expected FROM communication_attachment_chunks) ordered "
        "WHERE chunk_offset<>expected LIMIT 1").fetchone()
    invalid_totals = connection.execute("SELECT 1 FROM communication_attachments a LEFT JOIN "
        "(SELECT attachment_id,sum(octet_length(data)) size FROM communication_attachment_chunks GROUP BY attachment_id) c USING(attachment_id) "
        "WHERE a.state IN ('reserved','uploaded') AND a.received_bytes<>COALESCE(c.size,0) LIMIT 1").fetchone()
    if invalid_chunks or invalid_totals or invalid_order:
        raise SchemaAdoptionError(NAME, checksum, "damaged attachment staging frontier")
    for kind, result, proof, row in connection.execute("SELECT r.operation_kind,r.result_json,r.result_digest,to_jsonb(a) "
        "FROM communication_attachment_requests r JOIN communication_attachments a USING(attachment_id) "
        "WHERE r.tenant_id=a.tenant_id AND r.project_id=a.project_id AND r.viewer_key=a.viewer_key").fetchall():
        try:
            if digest(result) != proof:
                raise ValueError("receipt digest differs")
            if kind == "begin":
                parsed = UploadLease(**result)
                if parsed.attachment_id != row["attachment_id"] or parsed.revision > row["revision"]:
                    raise ValueError("receipt subject differs")
            elif kind in {"reserve", "complete", "ready", "reject"}:
                _contracts.validate("Attachment", result)
                if any(result[field] != row[column] for field, column in (("attachment_id", "attachment_id"), ("project_id", "project_id"),
                    ("name", "name"), ("media_type", "media_type"), ("bytes", "declared_bytes"), ("sha256", "declared_sha256"))):
                    raise ValueError("receipt declaration differs")
            elif type(result) is not dict or len(canonical(result).encode()) > 65536:
                raise ValueError("invalid facade plan metadata")
        except (ValueError, TypeError, KeyError) as error:
            raise SchemaAdoptionError(NAME, checksum, "damaged attachment request receipt") from error


def _ddl_checks(source):
    values = []
    for match in re.finditer(r"\bCHECK\s*\(", source):
        start, depth, quoted, position = match.end(), 1, False, match.end()
        while depth:
            character = source[position]
            if character == "'":
                quoted = not quoted
            elif not quoted and character in "()":
                depth += 1 if character == "(" else -1
            position += 1
        values.append(source[start:position - 1])
    return values


def _normalize_check(value):
    value = value.lower()
    value = re.sub(r'"([a-z_][a-z0-9_]*)"', r"\1", value)
    value = re.sub(r"(\w+\(\w+\)|\w+)\s+between\s+(\w+)\s+and\s+(\w+)", r"(\1>=\2 and \1<=\3)", value)
    value = re.sub(r"(\w+)\s+not\s+in\s*\(([^)]*)\)", r"\1<>all(array[\2])", value)
    value = re.sub(r"(\w+)\s+in\s*\(([^)]*)\)", r"\1=any(array[\2])", value)
    return re.sub(r"\s|[()]|::(?:text|bigint|integer|jsonb|bytea)(?:\[\])?", "", value)


def adopt_attachment_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-attachments:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if any(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None for table in TABLES):
            raise SchemaAdoptionError(NAME, checksum, "unversioned attachment storage")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit attachment migration required")
    _shape(connection, checksum)


def verify_attachment_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "attachment storage adoption required")
    _shape(connection, checksum)

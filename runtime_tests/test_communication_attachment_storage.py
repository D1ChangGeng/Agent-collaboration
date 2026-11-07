"""Private upload storage on real disposable PG; ArtifactRefs are CAS fixtures.

The typed reference fixtures establish metadata/CAS handoff fences only. Actual
CAS publication/content validation belong to integration outside SQL. No HTTP,
Native/model, arbitrary local path or URL is used by these storage tests.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from time import sleep

import psycopg
import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_attachment_storage import (
    TABLES,
    AttachmentCorrupt,
    AttachmentExpired,
    AttachmentIdentity,
    AttachmentLimits,
    AttachmentQuotaExceeded,
    AttachmentUploadConflict,
    adopt_attachment_storage,
    append_attachment_chunk,
    associate_attachments,
    attachment_request,
    begin_attachment_upload,
    complete_attachment_upload,
    expire_attachment_staging,
    finish_attachment_ready,
    get_attachment,
    message_attachment_artifact,
    owner_artifact,
    read_uploaded_attachment,
    reject_attachment,
    reserve_attachment,
    uploaded_attachment_lease,
    verify_attachment_storage,
)
from runtime.communication_client_service import CommunicationClientService
from runtime.errors import IdempotencyConflict, NotFound, RevisionConflict, SchemaAdoptionError
from runtime.models import ArtifactRef
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"
CONTRACTS = ClientContracts()
SMALL = AttachmentLimits(file_bytes=64, message_bytes=64, viewer_bytes=256, project_bytes=1024, chunk_bytes=4)


@pytest.fixture
def attachments(comm):
    with comm.authority._connect() as connection:
        adopt_attachment_storage(connection)
    return comm


def owner(f, name="a"):
    source = f.clients[name]
    own = CommunicationClientService(source.service, source.credential_provider())

    def selected(bound, cursor, _root, _command):
        address = source.service._communication_address(cursor, PROJECT)
        scope = cursor.execute("SELECT scope_id FROM grants WHERE grant_ref=%s", (bound.context.grant_ref,)).fetchone()[0]
        return AttachmentIdentity(bound.tenant_id, PROJECT, own._viewer_actor_ref(PROJECT, address), scope, address)

    return own._transaction(PROJECT, "read_message", selected)


def call(f, operation, *args, **kwargs):
    with f.authority._connect() as connection:
        return operation(connection.cursor(), *args, **kwargs)


def declare(data=b"abcdefghij", **changes):
    return {"name": "notes.txt", "media_type": "text/plain", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} | changes


def reserve(f, identity=None, data=b"abcdefghij", key="declare", limits=SMALL):
    return call(f, reserve_attachment, identity or owner(f), declare(data), key, limits=limits)


def upload(f, identity, metadata, data, *, suffix="one", limits=SMALL):
    identifier = metadata["attachment_id"]
    lease = call(f, begin_attachment_upload, identity, identifier, expected_revision=metadata["revision"], request_namespace="begin-" + suffix, limits=limits)
    for offset in range(0, len(data), lease.chunk_bytes):
        call(f, append_attachment_chunk, identity, identifier, lease, offset, data[offset:offset + lease.chunk_bytes])
    done = call(f, complete_attachment_upload, identity, identifier, lease, "complete-" + suffix)
    return lease, done


def artifact(metadata):
    checksum = metadata["sha256"]
    return ArtifactRef(path=checksum[:2] + "/" + checksum, sha256=checksum, size_bytes=metadata["bytes"],
                       media_type=metadata["media_type"], scope_id="local-scope", immutable=True)


def ready(f, identity=None, data=b"abcdefghij", suffix="one", limits=SMALL):
    identity = identity or owner(f)
    meta = reserve(f, identity, data, "declare-" + suffix, limits)
    lease, done = upload(f, identity, meta, data, suffix=suffix, limits=limits)
    result = call(f, finish_attachment_ready, identity, meta["attachment_id"], lease, artifact(meta),
                  expected_revision=done["revision"], request_namespace="ready-" + suffix)
    return meta, lease, done, result


def rows(f, table=TABLES[0]):
    with f.authority._connect() as connection:
        return connection.execute("SELECT to_jsonb(t) FROM " + table + " t ORDER BY to_jsonb(t)::text").fetchall()


def test_missing_adoption_is_explicit_and_does_not_adopt_or_damage_core(comm):
    with comm.authority._connect() as connection:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_attachment_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert all(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone() == (None,) for table in TABLES)
    assert send(comm, activation="message_only")["ok"]


def test_adoption_and_verification_preserve_reserved_metadata_and_receipts(attachments):
    f = attachments
    reserve(f)
    before = [rows(f, table) for table in TABLES]
    with f.authority._connect() as connection:
        verify_attachment_storage(connection)
        adopt_attachment_storage(connection)
    assert [rows(f, table) for table in TABLES] == before


def test_reservation_id_is_not_digest_and_exact_outcomes_survive_lifecycle_and_config_changes(attachments):
    f, identity = attachments, owner(attachments)
    original = reserve(f, identity)
    second = reserve(f, identity, key="other-key")
    assert original["attachment_id"] != second["attachment_id"] and original["sha256"] == second["sha256"]
    changed_internal = replace(SMALL, chunk_bytes=8)
    assert reserve(f, identity, limits=changed_internal) == original
    with pytest.raises(IdempotencyConflict):
        call(f, reserve_attachment, identity, declare(b"different"), "declare", limits=SMALL)
    lease, done = upload(f, identity, original, b"abcdefghij")
    accepted = call(f, finish_attachment_ready, identity, original["attachment_id"], lease, artifact(original),
                    expected_revision=done["revision"], request_namespace="ready")
    assert reserve(f, identity) == original
    assert call(f, complete_attachment_upload, identity, original["attachment_id"], lease, "complete-one") == done
    assert call(f, finish_attachment_ready, identity, original["attachment_id"], lease, artifact(original),
                expected_revision=done["revision"], request_namespace="ready") == accepted
    assert call(f, get_attachment, identity, original["attachment_id"])["state"] == "ready"
    with pytest.raises((RevisionConflict, AttachmentUploadConflict)):
        call(f, begin_attachment_upload, identity, original["attachment_id"], expected_revision=1, request_namespace="stale-ready", limits=SMALL)


def test_verified_uploaded_bytes_and_immutable_ready_metadata_are_private(attachments):
    f, identity = attachments, owner(attachments)
    data = b"abcdefghij"
    meta = reserve(f, identity, data)
    lease, done = upload(f, identity, meta, data)
    current = call(f, uploaded_attachment_lease, identity, meta["attachment_id"])
    verified = call(f, read_uploaded_attachment, identity, meta["attachment_id"], current, expected_revision=current.revision)
    assert verified.data == data and current.revision == done["revision"]
    result = call(f, finish_attachment_ready, identity, meta["attachment_id"], lease, artifact(meta),
                  expected_revision=verified.attachment["revision"], request_namespace="publish-ready")
    CONTRACTS.validate("Attachment", result)
    assert result["state"] == "ready" and result["upload_path"] is None
    assert rows(f, TABLES[1]) == []
    assert call(f, owner_artifact, identity, meta["attachment_id"]) == artifact(meta)
    for operation in (get_attachment, owner_artifact):
        with pytest.raises(NotFound):
            call(f, operation, owner(f, "b"), meta["attachment_id"])
    with f.authority._connect() as connection, pytest.raises(psycopg.Error):
        connection.execute("UPDATE communication_attachments SET name='mutated',revision=revision+1 WHERE attachment_id=%s", (meta["attachment_id"],))
    assert not any(driver.calls for driver in f.drivers.values())


@pytest.mark.parametrize("change", ["viewer", "tenant", "project", "address", "scope"])
def test_metadata_never_crosses_caller_identity_boundaries(attachments, change):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    wrong = {"viewer": replace(identity, viewer_key=owner(f, "b").viewer_key), "tenant": replace(identity, tenant_id="foreign-tenant"),
        "project": replace(identity, project_id="foreign-project"), "address": replace(identity, owner_address=owner(f, "b").owner_address),
        "scope": replace(identity, scope_id="foreign-scope")}[change]
    with pytest.raises(NotFound):
        call(f, get_attachment, wrong, metadata["attachment_id"])


@pytest.mark.parametrize("quota", ["viewer", "project"])
def test_reservation_quota_is_serialized_under_concurrent_requests(attachments, quota):
    f = attachments
    identities = [owner(f), owner(f, "b")]
    limits = replace(SMALL, viewer_bytes=10 if quota == "viewer" else 100, project_bytes=100 if quota == "viewer" else 10)

    def racing(number):
        identity = identities[0] if quota == "viewer" else identities[number % 2]
        try:
            return reserve(f, identity, b"123456", "racing-" + str(number), limits)
        except AttachmentQuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(racing, range(6)))
    assert sum(result is not None for result in results) == 1
    assert len(rows(f)) == len(rows(f, TABLES[2])) == 1


def test_concurrent_same_key_reserves_only_one_resource(attachments):
    f, identity = attachments, owner(attachments)
    with ThreadPoolExecutor(max_workers=5) as pool:
        result = list(pool.map(lambda _number: reserve(f, identity), range(5)))
    assert all(value == result[0] for value in result)
    assert len(rows(f)) == len(rows(f, TABLES[2])) == 1


def test_chunks_require_exact_order_boundaries_and_original_replay_bytes(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    identifier = metadata["attachment_id"]
    lease = call(f, begin_attachment_upload, identity, identifier, expected_revision=1, request_namespace="begin", limits=SMALL)
    for offset, data in ((4, b"efgh"), (0, b"abcde"), (8, b"ijklm")):
        with pytest.raises(AttachmentUploadConflict):
            call(f, append_attachment_chunk, identity, identifier, lease, offset, data)
    first = call(f, append_attachment_chunk, identity, identifier, lease, 0, b"abcd")
    call(f, append_attachment_chunk, identity, identifier, lease, 4, b"efgh")
    assert call(f, append_attachment_chunk, identity, identifier, lease, 0, b"abcd") == first
    with pytest.raises(AttachmentUploadConflict):
        call(f, append_attachment_chunk, identity, identifier, lease, 0, b"xxxx")
    assert len(rows(f, TABLES[1])) == 2


def test_interrupted_full_put_replays_offset_zero_using_captured_chunk_size(attachments):
    f, identity = attachments, owner(attachments)
    meta = reserve(f, identity)
    identifier = meta["attachment_id"]
    lease = call(f, begin_attachment_upload, identity, identifier, expected_revision=1, request_namespace="begin", limits=SMALL)
    receipt = call(f, append_attachment_chunk, identity, identifier, lease, 0, b"abcd")
    metadata = call(f, get_attachment, identity, identifier)
    resumed = call(f, begin_attachment_upload, identity, identifier, expected_revision=metadata["revision"], request_namespace="resume-device",
                   limits=replace(SMALL, chunk_bytes=8))
    assert resumed.generation == lease.generation and resumed.token == lease.token and resumed.chunk_bytes == 4
    assert call(f, append_attachment_chunk, identity, identifier, resumed, 0, b"abcd") == receipt
    call(f, append_attachment_chunk, identity, identifier, resumed, 4, b"efgh")
    call(f, append_attachment_chunk, identity, identifier, resumed, 8, b"ij")
    assert call(f, complete_attachment_upload, identity, identifier, resumed, "resumed-complete")["state"] == "uploaded"


def test_digest_mismatch_never_becomes_uploaded_and_restart_fences_old_generation(attachments):
    f, identity = attachments, owner(attachments)
    meta = reserve(f, identity, b"abcdefgh")
    identifier = meta["attachment_id"]
    lease = call(f, begin_attachment_upload, identity, identifier, expected_revision=1, request_namespace="begin", limits=SMALL)
    call(f, append_attachment_chunk, identity, identifier, lease, 0, b"xxxx")
    call(f, append_attachment_chunk, identity, identifier, lease, 4, b"yyyy")
    with pytest.raises(AttachmentUploadConflict):
        call(f, complete_attachment_upload, identity, identifier, lease, "wrong-complete")
    old = call(f, get_attachment, identity, identifier)
    assert old["state"] == "reserved"
    restarted = call(f, begin_attachment_upload, identity, identifier, expected_revision=old["revision"], request_namespace="restart", restart=True, limits=SMALL)
    assert restarted.generation == lease.generation + 1 and rows(f, TABLES[1]) == []
    with pytest.raises(AttachmentUploadConflict):
        call(f, append_attachment_chunk, identity, identifier, lease, 0, b"abcd")


@pytest.mark.parametrize("invalid", ["untyped", "sha", "size", "scope", "path", "mutable", "media"])
def test_ready_requires_exact_typed_immutable_scope_artifact(attachments, invalid):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    lease, uploaded = upload(f, identity, metadata, b"abcdefghij")
    ref = artifact(metadata)
    changes = {"sha": {"sha256": "a" * 64}, "size": {"size_bytes": 1}, "scope": {"scope_id": "another-scope"},
               "path": {"path": "different/object"}, "mutable": {"immutable": False}, "media": {"media_type": "image/png"}}
    ref = ref.model_dump() if invalid == "untyped" else ref.model_copy(update=changes[invalid])
    with pytest.raises((TypeError, ValueError, AttachmentCorrupt)):
        call(f, finish_attachment_ready, identity, metadata["attachment_id"], lease, ref, expected_revision=uploaded["revision"], request_namespace="bad-ready")
    assert call(f, get_attachment, identity, metadata["attachment_id"])["state"] == "uploaded"


def test_finalizer_cannot_use_captured_revision_after_new_upload_generation(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    lease, uploaded = upload(f, identity, metadata, b"abcdefghij")
    captured = call(f, read_uploaded_attachment, identity, metadata["attachment_id"], lease, expected_revision=uploaded["revision"])
    call(f, begin_attachment_upload, identity, metadata["attachment_id"], expected_revision=uploaded["revision"], request_namespace="new-generation", restart=True, limits=SMALL)
    with pytest.raises((RevisionConflict, AttachmentUploadConflict)):
        call(f, finish_attachment_ready, identity, metadata["attachment_id"], lease, artifact(metadata),
             expected_revision=captured.attachment["revision"], request_namespace="late-finalize")
    assert call(f, get_attachment, identity, metadata["attachment_id"])["state"] == "reserved"


def test_expiration_cleanup_wins_late_finalizer_and_keeps_original_retry_outcome(attachments):
    f, identity = attachments, owner(attachments)
    limits = replace(SMALL, reservation_ttl_seconds=1)
    metadata = reserve(f, identity, b"abcd", limits=limits)
    lease, uploaded = upload(f, identity, metadata, b"abcd", limits=limits)
    sleep(1.05)
    with f.authority._connect() as connection:
        assert expire_attachment_staging(connection, tenant_id=identity.tenant_id, limit=1) == 1
    assert call(f, get_attachment, identity, metadata["attachment_id"])["state"] == "expired"
    assert reserve(f, identity, b"abcd", limits=limits) == metadata
    with pytest.raises(AttachmentExpired):
        call(f, finish_attachment_ready, identity, metadata["attachment_id"], lease, artifact(metadata),
             expected_revision=uploaded["revision"], request_namespace="late-ready")
    assert rows(f, TABLES[1]) == []


def test_ready_association_checks_all_limits_sender_and_ownership_before_any_pin(attachments):
    f, identity = attachments, owner(attachments)
    first = ready(f, identity, b"abcd", "first")[3]
    second = ready(f, identity, b"efgh", "second")[3]
    third = ready(f, identity, b"ijkl", "third")[3]
    ids = [first["attachment_id"], second["attachment_id"], third["attachment_id"]]
    message = send(f, activation="message_only")["data"]
    for selected, limits in ((ids, replace(SMALL, attachments_per_message=2)), (ids[:2], replace(SMALL, message_bytes=7))):
        with pytest.raises((ValueError, AttachmentQuotaExceeded)):
            call(f, associate_attachments, identity, message["message_id"], selected, limits=limits)
        assert not any(row[0]["pinned"] for row in rows(f))
    foreign = send(f, "b", "c", activation="message_only")["data"]
    with pytest.raises(NotFound):
        call(f, associate_attachments, identity, foreign["message_id"], ids[:1], limits=SMALL)
    refs = call(f, associate_attachments, identity, message["message_id"], ids[:2], limits=SMALL)
    before = rows(f)
    assert call(f, associate_attachments, identity, message["message_id"], ids[:2], limits=SMALL) == refs
    assert rows(f) == before
    with pytest.raises(AttachmentUploadConflict):
        call(f, associate_attachments, identity, message["message_id"], list(reversed(ids[:2])), limits=SMALL)
    for row in rows(f):
        if row[0]["attachment_id"] in ids[:2]:
            assert row[0]["pinned"] and row[0]["expires_at"] is None
    ref, cas = call(f, message_attachment_artifact, identity.tenant_id, PROJECT, owner(f, "b").owner_address, message["message_id"], ids[0])
    assert ref == refs[0] and cas.sha256 == first["sha256"]
    with pytest.raises(NotFound):
        call(f, message_attachment_artifact, identity.tenant_id, PROJECT, owner(f, "c").owner_address, message["message_id"], ids[0])
    assert call(f, get_attachment, identity, ids[0])["state"] == "ready"


def test_pinned_content_is_not_expired_and_cleanup_is_bounded(attachments):
    f, identity = attachments, owner(attachments)
    pinned = ready(f, identity, b"abcd", "pinned")[3]
    message = send(f, activation="message_only")["data"]
    call(f, associate_attachments, identity, message["message_id"], [pinned["attachment_id"]], limits=SMALL)
    limits = replace(SMALL, reservation_ttl_seconds=1)
    for number in range(3):
        reserve(f, identity, b"abcd", "expiring-" + str(number), limits)
    sleep(1.05)
    with f.authority._connect() as connection:
        assert expire_attachment_staging(connection, tenant_id=identity.tenant_id, limit=1) == 1
        assert connection.execute("SELECT count(*) FROM communication_attachments WHERE state='expired'").fetchone() == (1,)
        assert expire_attachment_staging(connection, tenant_id=identity.tenant_id, limit=100) == 2
    assert call(f, owner_artifact, identity, pinned["attachment_id"]).sha256 == pinned["sha256"]
    assert call(f, get_attachment, identity, pinned["attachment_id"])["expires_at"] is None


def test_caller_rollback_removes_reservation_receipt_and_staged_changes(attachments):
    f, identity = attachments, owner(attachments)
    with f.authority._connect() as connection:
        reserve_attachment(connection.cursor(), identity, declare(), "rolled-back", limits=SMALL)
        connection.rollback()
    assert all(rows(f, table) == [] for table in TABLES)


def test_generic_request_captures_stable_plan_once_after_revision_changes(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    identifier, body = metadata["attachment_id"], {"sha256": metadata["sha256"], "bytes": metadata["bytes"], "media_type": metadata["media_type"]}
    plans = []

    def prepare(cursor):
        plans.append(True)
        lease = begin_attachment_upload(cursor, identity, identifier, expected_revision=1, request_namespace="internal-begin", limits=SMALL)
        return {"lease": asdict(lease), "expected_revision": lease.revision}

    first = call(f, attachment_request, identity, identifier, "http-plan", "http.upload.plan", body, prepare)
    lease = call(f, begin_attachment_upload, identity, identifier, expected_revision=1, request_namespace="internal-begin", limits=SMALL)
    call(f, append_attachment_chunk, identity, identifier, lease, 0, b"abcd")
    assert call(f, attachment_request, identity, identifier, "http-plan", "http.upload.plan", body, prepare) == first
    assert plans == [True]
    with pytest.raises(IdempotencyConflict):
        call(f, attachment_request, identity, identifier, "http-plan", "http.upload.plan", body | {"bytes": 1})
    before = rows(f, TABLES[2])
    assert call(f, attachment_request, identity, identifier, "read-only-miss", "http.upload.result", body) is None
    assert rows(f, TABLES[2]) == before


def test_generic_request_concurrent_once_and_callback_rollback(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    attempts = []

    def prepare(_cursor):
        attempts.append(True)
        return {"captured_revision": 1}

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _number: call(f, attachment_request, identity, metadata["attachment_id"],
            "same-plan", "http.finalize.plan", {"bytes": 10}, prepare), range(5)))
    assert attempts == [True] and all(value == responses[0] for value in responses)

    def failed(cursor):
        begin_attachment_upload(cursor, identity, metadata["attachment_id"], expected_revision=1, request_namespace="rollback-begin", limits=SMALL)
        raise OSError("controlled SQL-plan failure")

    with pytest.raises(OSError):
        call(f, attachment_request, identity, metadata["attachment_id"], "bad-plan", "http.upload.plan", {}, failed)
    assert call(f, get_attachment, identity, metadata["attachment_id"])["revision"] == 1
    assert call(f, attachment_request, identity, metadata["attachment_id"], "bad-plan", "http.upload.plan", {}) is None


def test_uploaded_lease_is_read_only_and_rejects_reserved_ready_or_expired(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    with pytest.raises(AttachmentUploadConflict):
        call(f, uploaded_attachment_lease, identity, metadata["attachment_id"])
    lease, done = upload(f, identity, metadata, b"abcdefghij")
    before = rows(f)
    captured = call(f, uploaded_attachment_lease, identity, metadata["attachment_id"])
    assert captured.revision == done["revision"] and rows(f) == before
    call(f, finish_attachment_ready, identity, metadata["attachment_id"], lease, artifact(metadata),
         expected_revision=done["revision"], request_namespace="done")
    with pytest.raises(AttachmentUploadConflict):
        call(f, uploaded_attachment_lease, identity, metadata["attachment_id"])


def test_external_content_rejection_is_explicit_and_cannot_reject_ready_content(attachments):
    f, identity = attachments, owner(attachments)
    metadata = reserve(f, identity)
    rejected = call(f, reject_attachment, identity, metadata["attachment_id"], expected_revision=1, request_namespace="validator-rejected")
    assert rejected["state"] == "rejected"
    assert call(f, reject_attachment, identity, metadata["attachment_id"], expected_revision=1, request_namespace="validator-rejected") == rejected
    ready_meta = ready(f, identity, b"abcd", "separate")[3]
    with pytest.raises(AttachmentUploadConflict):
        call(f, reject_attachment, identity, ready_meta["attachment_id"], expected_revision=ready_meta["revision"], request_namespace="cannot-reject-ready")


@pytest.mark.parametrize("damage", ["column", "key", "check", "trigger", "generated", "function", "foreign_key"])
def test_schema_damage_refuses_read_only_verify_and_re_adoption(attachments, damage):
    f = attachments
    with f.authority._connect() as connection:
        commands = {"column": "ALTER TABLE communication_attachments DROP COLUMN pinned",
            "key": "ALTER TABLE communication_attachment_chunks DROP CONSTRAINT communication_attachment_chunks_pkey",
            "check": "ALTER TABLE communication_attachments DROP CONSTRAINT attachment_state",
            "trigger": "ALTER TABLE communication_attachments DISABLE TRIGGER acs_attachment_immutable",
            "generated": "ALTER TABLE communication_attachment_requests ALTER COLUMN request_hash DROP EXPRESSION",
            "function": "ALTER FUNCTION acs_attachment_request_hash(text) VOLATILE"}
        if damage == "foreign_key":
            name = connection.execute("SELECT conname FROM pg_constraint WHERE conrelid=to_regclass('communication_message_attachments') "
                                      "AND confrelid=to_regclass('communication_messages')").fetchone()[0]
            connection.execute(psycopg.sql.SQL("ALTER TABLE communication_message_attachments DROP CONSTRAINT {}").format(psycopg.sql.Identifier(name)))
        else:
            connection.execute(commands[damage])
    for operation in (verify_attachment_storage, adopt_attachment_storage):
        with f.authority._connect() as connection, pytest.raises(SchemaAdoptionError):
            operation(connection)

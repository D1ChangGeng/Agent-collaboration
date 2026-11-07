"""Actual private attachment facade, staged PG bytes and existing platform CAS.

No model, deployment or Native input is used. File stores are private temporary
Scope stores; SQL/byte interleavings operate on actual PostgreSQL transactions.
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from threading import Barrier

import psycopg
import pytest

import runtime.communication_client_attachments as facade_module
from runtime import communication_attachment_storage as storage
from runtime.artifacts import LocalArtifactStore, WindowsArtifactStore
from runtime.client_contracts import ClientContracts
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_http import CommunicationHttpError
from runtime.surface_config import CommunicationAttachmentSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_attachment_content import png
from runtime_tests.test_notification_continuity import shared_principal_clients

comm = comm_fixture
PROJECT = "project-alpha"
CONTRACTS = ClientContracts()


def bind(f):
    for source in f.clients.values():
        authority = source.service.service.authority
        authority._communication_attachments_enabled = True
        authority._communication_attachment_settings = f.attachment_settings
        authority._artifact_store = f.attachment_store
        source.service.artifacts = f.attachment_store
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions||'\"artifact.read\"'::jsonb||'\"artifact.write\"'::jsonb WHERE tenant_id=%s", (f.authority.tenant_id,))


@pytest.fixture
def attached(comm, tmp_path):
    root = tmp_path / "private-cas"
    if os.name == "nt":
        from runtime_tests.test_windows_artifact_store import _private
        _private(root)
        backend = WindowsArtifactStore
    elif sys.platform.startswith("linux"):
        backend = LocalArtifactStore
    else:
        pytest.skip("no existing admitted CAS backend for this platform")
    with backend(root, "local-scope", max_bytes=256 * 1024) as store:
        comm.attachment_store = store
        comm.attachment_settings = CommunicationAttachmentSettings(file_bytes=256 * 1024, message_bytes=512 * 1024,
            viewer_staging_bytes=1024 * 1024, project_staging_bytes=4 * 1024 * 1024)
        bind(comm)
        with psycopg.connect(comm.dsn) as connection:
            storage.adopt_attachment_storage(connection)
        yield comm


def client(f, name="a"):
    source = f.clients[name]
    return CommunicationClientService(source.service, source.credential_provider())


def declare(data, *, media_type="text/plain", name="notes.txt"):
    return {"name": name, "media_type": media_type, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def reserve(service, data=b"attachment bytes", *, key="reserve", **kwargs):
    value = service.create_attachment(PROJECT, declare(data, **kwargs), client_request_id=key)
    CONTRACTS.validate("Attachment", value)
    return value


def upload(service, attachment, data, *, key="upload"):
    context = service.begin_attachment_upload(PROJECT, attachment["attachment_id"], content_type="application/octet-stream", client_request_id=key)
    revision = context.lease.revision
    for offset in range(0, len(data), context.lease.chunk_bytes):
        result = service.append_attachment_upload(context, offset, data[offset:offset + context.lease.chunk_bytes])
        if result is not None:
            revision = result["revision"]
    completed = service.complete_attachment_upload(context, observed_bytes=len(data), observed_sha256=hashlib.sha256(data).hexdigest(), last_revision=revision)
    return context, completed


def ready(service, data=b"attachment bytes", *, key="resource", **kwargs):
    attachment = reserve(service, data, key=key + "-reserve", **kwargs)
    _context, completed = upload(service, attachment, data, key=key + "-upload")
    result = service.finalize_attachment(PROJECT, attachment["attachment_id"],
        {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}, client_request_id=key + "-finalize")
    assert completed["state"] == "uploaded" and result["state"] == "ready"
    return result


def row(f, attachment_id):
    with psycopg.connect(f.dsn) as connection:
        return connection.execute("SELECT to_jsonb(a) FROM communication_attachments a WHERE attachment_id=%s", (attachment_id,)).fetchone()[0]


def associate(f, service, attachment_id, *, recipient="collaborator:project-alpha:slot-b"):
    # Compose the existing Core send and storage association on one borrowed
    # transaction; no attachment field is added to a legacy signed packet.
    with f.authority.transaction() as (bound, connection):
        shared = copy(service.project_service.service)
        shared.authority = bound
        projects = copy(service.project_service)
        projects.service = shared
        _state, sent, _actions = projects.execute("send_message", {"project_id": PROJECT, "to": recipient,
            "content": "Message pins an explicit attachment", "activation": "message_only", "client_request_id": uuid.uuid4().hex}, service.credential)
        with connection.cursor() as cursor:
            actual, root, _command = projects._authorize(bound, cursor, PROJECT, "read_message", {"project_id": PROJECT})
            owner = service._attachment_owner(actual, cursor, root, PROJECT)
            storage.associate_attachments(cursor, owner, sent["message_id"], [attachment_id], limits=f.attachment_settings.to_limits())
        return sent


@pytest.mark.parametrize("data,media_type,name", [("Verified attachment 汉字🧭".encode(), "TEXT/PLAIN; charset=UTF-8", "汉字 notes.txt"),
    (b'{"file":true}', "application/json", "object.json"), (png(), "image/png", "pixel.png")], ids=["text", "json", "png"])
def test_owner_reservation_metadata_and_ready_platform_cas_download(attached, data, media_type, name):
    service = client(attached)
    value = ready(service, data, name=name, media_type=media_type)
    expected_type = media_type.split(";")[0].lower()
    assert value["media_type"] == expected_type and service.attachment(PROJECT, value["attachment_id"]) == value
    downloaded = service.download_attachment(PROJECT, value["attachment_id"])
    assert downloaded.data == data and downloaded.sha256 == hashlib.sha256(data).hexdigest()
    assert downloaded.media_type == expected_type and downloaded.content_disposition.isascii()
    assert downloaded.content_disposition.startswith("attachment;")
    assert not any(driver.calls for driver in attached.drivers.values())


def test_upload_plan_survives_counter_advance_interruption_and_ready_exact_replay(attached):
    service, data = client(attached), b"a" * 65536 + b"last bytes"
    reservation = reserve(service, data)
    first = service.begin_attachment_upload(PROJECT, reservation["attachment_id"], content_type="application/octet-stream", client_request_id="stable-upload")
    chunk = service.append_attachment_upload(first, 0, data[:65536])
    resumed = service.begin_attachment_upload(PROJECT, reservation["attachment_id"], content_type="application/octet-stream", client_request_id="stable-upload")
    assert resumed.lease == first.lease and resumed.attachment == first.attachment
    assert service.append_attachment_upload(resumed, 0, data[:65536]) == chunk
    final_chunk = service.append_attachment_upload(resumed, 65536, data[65536:])
    completed = service.complete_attachment_upload(resumed, observed_bytes=len(data), observed_sha256=reservation["sha256"], last_revision=final_chunk["revision"])
    finalized = service.finalize_attachment(PROJECT, reservation["attachment_id"], {"bytes": len(data), "sha256": reservation["sha256"]}, client_request_id="finalize")
    repeat = service.begin_attachment_upload(PROJECT, reservation["attachment_id"], content_type="application/octet-stream", client_request_id="stable-upload")
    assert repeat.lease == first.lease and repeat.prior_result is not None
    assert service.append_attachment_upload(repeat, 0, data[:65536]) is None
    assert service.complete_attachment_upload(repeat, observed_bytes=len(data), observed_sha256=reservation["sha256"], last_revision=first.lease.revision) == completed
    with pytest.raises(CommunicationHttpError) as changed:
        service.complete_attachment_upload(repeat, observed_bytes=len(data), observed_sha256="0" * 64, last_revision=first.lease.revision)
    assert changed.value.code == "idempotency_conflict" and changed.value.status_code == 409
    assert service.attachment(PROJECT, reservation["attachment_id"]) == finalized
    with psycopg.connect(attached.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_attachment_chunks WHERE attachment_id=%s", (reservation["attachment_id"],)).fetchone()[0] == 0


def test_wrong_observed_digest_records_rejection_and_bad_mime_never_becomes_ready(attached):
    service, data = client(attached), b"not an image"
    declaration = reserve(service, data, key="bad-digest")
    context = service.begin_attachment_upload(PROJECT, declaration["attachment_id"], content_type="application/octet-stream", client_request_id="wrong-digest")
    chunk = service.append_attachment_upload(context, 0, data)
    with pytest.raises(CommunicationHttpError) as rejected:
        service.complete_attachment_upload(context, observed_bytes=len(data), observed_sha256="0" * 64, last_revision=chunk["revision"])
    assert rejected.value.status_code in {400, 409}
    assert row(attached, declaration["attachment_id"])["state"] == "rejected"
    declaration = reserve(service, data, key="bad-format", media_type="image/png")
    upload(service, declaration, data, key="bad-format-upload")
    with pytest.raises(CommunicationHttpError) as bad_type:
        service.finalize_attachment(PROJECT, declaration["attachment_id"], {"bytes": len(data), "sha256": declaration["sha256"]}, client_request_id="bad-format-finalize")
    assert bad_type.value.status_code == 400
    actual = row(attached, declaration["attachment_id"])
    assert actual["state"] == "rejected" and actual["artifact_json"] is None


def test_different_finalize_keys_converge_on_same_ready_resource(attached, monkeypatch):
    service, data = client(attached), b"one immutable ready resource"
    declaration = reserve(service, data)
    upload(service, declaration, data)
    barrier = Barrier(2)
    original = facade_module.put_attachment_content

    def published(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(facade_module, "put_attachment_content", published)

    def finalize(key):
        return service.finalize_attachment(PROJECT, declaration["attachment_id"], {"bytes": len(data), "sha256": declaration["sha256"]}, client_request_id=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finalize, ("finalizer-a", "finalizer-b")))
    assert results[0] == results[1] == service.attachment(PROJECT, declaration["attachment_id"])
    assert results[0]["state"] == "ready"


def test_same_principal_slots_and_root_manager_cannot_read_private_uploads(attached):
    shared_principal_clients(attached)
    bind(attached)
    first, second, manager = client(attached, "shared-1"), client(attached, "shared-2"), client(attached)
    value = ready(first, b"viewer private", key="shared")
    assert first.attachment(PROJECT, value["attachment_id"])["state"] == "ready"
    for outsider in (second, manager):
        for operation in (outsider.attachment, outsider.download_attachment):
            with pytest.raises(CommunicationHttpError) as denied:
                operation(PROJECT, value["attachment_id"])
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    own_second = reserve(second, b"other viewer", key="shared-reserve")
    assert own_second["attachment_id"] != value["attachment_id"]


def test_message_participant_download_starts_only_after_atomic_actual_association(attached):
    owner, participant, outsider = client(attached), client(attached, "b"), client(attached, "c")
    data = b"message-authorized bytes"
    value = ready(owner, data)
    with pytest.raises(CommunicationHttpError) as private:
        participant.download_attachment(PROJECT, value["attachment_id"])
    assert private.value.status_code == 404
    message = associate(attached, owner, value["attachment_id"])
    assert participant.download_attachment(PROJECT, value["attachment_id"]).data == data
    with pytest.raises(CommunicationHttpError) as unrelated:
        outsider.download_attachment(PROJECT, value["attachment_id"])
    assert unrelated.value.status_code == 404
    with psycopg.connect(attached.dsn) as connection:
        assert connection.execute("SELECT attachment_id FROM communication_message_attachments WHERE message_id=%s", (message["message_id"],)).fetchone() == (value["attachment_id"],)
    assert not any(driver.calls for driver in attached.drivers.values())


def test_upload_finalize_wrong_owner_or_project_are_not_found(attached):
    owner, wrong, data = client(attached), client(attached, "b"), b"private plan"
    value = reserve(owner, data)
    for service, project in ((wrong, PROJECT), (owner, "unknown-project")):
        with pytest.raises(CommunicationHttpError) as upload_denied:
            service.begin_attachment_upload(project, value["attachment_id"], content_type="application/octet-stream", client_request_id="wrong-upload")
        assert upload_denied.value.status_code == 404
        with pytest.raises(CommunicationHttpError) as finalize_denied:
            service.finalize_attachment(project, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="wrong-finalize")
        assert finalize_denied.value.status_code == 404


def test_reservation_quota_has_no_new_effect_or_partial_rows(attached):
    attached.attachment_settings = CommunicationAttachmentSettings(file_bytes=8, message_bytes=8, viewer_staging_bytes=8, project_staging_bytes=16)
    bind(attached)
    service = client(attached)
    reserve(service, b"12345678", key="first-budget")
    with pytest.raises(CommunicationHttpError) as rejected:
        reserve(service, b"x", key="over-budget")
    assert rejected.value.status_code == 429 and rejected.value.effect_state == "none"
    with psycopg.connect(attached.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_attachments").fetchone()[0] == 1


def test_cas_publication_is_outside_sql_and_grant_revocation_before_ready_fails_closed(attached, monkeypatch):
    service, data = client(attached), b"finalize fence"
    value = reserve(service, data)
    upload(service, value, data)
    original = facade_module.put_attachment_content

    def revoke_after_cas(*args, **kwargs):
        with psycopg.connect(attached.dsn) as writer:
            writer.execute("SELECT attachment_id FROM communication_attachments WHERE attachment_id=%s FOR UPDATE NOWAIT", (value["attachment_id"],))
            writer.execute("SELECT grant_ref FROM grants WHERE grant_ref=%s FOR UPDATE NOWAIT", (service.project_service.context.grant_ref,))
        artifact = original(*args, **kwargs)
        with psycopg.connect(attached.dsn) as revoked:
            revoked.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (service.project_service.context.grant_ref,))
        return artifact

    monkeypatch.setattr(facade_module, "put_attachment_content", revoke_after_cas)
    with pytest.raises(CommunicationHttpError) as denied:
        service.finalize_attachment(PROJECT, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="revoke-finalize")
    assert denied.value.status_code == 403
    actual = row(attached, value["attachment_id"])
    assert actual["state"] == "uploaded" and actual["artifact_json"] is None


def test_download_rechecks_live_artifact_permission_after_cas_read(attached, monkeypatch):
    service, data = client(attached), b"download permission fence"
    value = ready(service, data)
    original = facade_module.read_attachment_content

    def revoke(*args, **kwargs):
        verified = original(*args, **kwargs)
        with psycopg.connect(attached.dsn) as connection:
            connection.execute("UPDATE grants SET permissions=permissions-'artifact.read' WHERE grant_ref=%s", (service.project_service.context.grant_ref,))
        return verified

    monkeypatch.setattr(facade_module, "read_attachment_content", revoke)
    with pytest.raises(CommunicationHttpError) as denied:
        service.download_attachment(PROJECT, value["attachment_id"])
    assert denied.value.status_code == 403


def test_bad_cas_ref_and_corruption_do_not_publish_or_release_bytes(attached, monkeypatch):
    service, data = client(attached), b"CAS integrity fence"
    value = reserve(service, data)
    upload(service, value, data)
    original = attached.attachment_store.put_bytes

    def wrong_ref(*args, **kwargs):
        return original(*args, **kwargs).model_copy(update={"scope_id": "another-scope"})

    monkeypatch.setattr(attached.attachment_store, "put_bytes", wrong_ref)
    with pytest.raises(CommunicationHttpError) as failed:
        service.finalize_attachment(PROJECT, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="retry-finalize")
    assert failed.value.status_code == 503 and row(attached, value["attachment_id"])["state"] == "uploaded"
    monkeypatch.setattr(attached.attachment_store, "put_bytes", original)
    completed = service.finalize_attachment(PROJECT, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="retry-finalize")
    metadata = row(attached, value["attachment_id"])
    path = attached.attachment_store.root / metadata["artifact_json"]["path"]
    path.chmod(0o600)
    path.write_bytes(b"corrupted controlled artifact")
    with pytest.raises(CommunicationHttpError) as corrupt:
        service.download_attachment(PROJECT, completed["attachment_id"])
    assert corrupt.value.status_code == 503


def test_ready_transition_and_final_result_receipt_commit_atomically(attached, monkeypatch):
    service, data = client(attached), b"ready result atomicity"
    value = reserve(service, data)
    upload(service, value, data)
    original = storage._receipt

    def fail_result(cursor, owner, namespace, kind, body, attachment_id, result):
        if kind == "finalize_result":
            raise RuntimeError("controlled receipt transaction failure")
        return original(cursor, owner, namespace, kind, body, attachment_id, result)

    monkeypatch.setattr(storage, "_receipt", fail_result)
    with pytest.raises(CommunicationHttpError):
        service.finalize_attachment(PROJECT, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="atomic-finalize")
    actual = row(attached, value["attachment_id"])
    assert actual["state"] == "uploaded" and actual["artifact_json"] is None
    monkeypatch.setattr(storage, "_receipt", original)
    assert service.finalize_attachment(PROJECT, value["attachment_id"], {"bytes": len(data), "sha256": value["sha256"]}, client_request_id="atomic-finalize")["state"] == "ready"


def test_cleanup_preserves_pinned_accepted_blob_and_participant_download(attached):
    service, data = client(attached), b"pinned accepted bytes"
    value = ready(service, data)
    associate(attached, service, value["attachment_id"])
    unused = reserve(service, b"unused", key="expired-unused")
    with psycopg.connect(attached.dsn) as connection:
        connection.execute("UPDATE communication_attachments SET expires_at=clock_timestamp()-interval '1 second',revision=revision+1 WHERE attachment_id=%s", (unused["attachment_id"],))
        assert storage.expire_attachment_staging(connection, tenant_id=attached.authority.tenant_id, project_id=PROJECT, limit=10) == 1
    pinned = row(attached, value["attachment_id"])
    assert pinned["pinned"] is True and pinned["state"] == "ready" and pinned["expires_at"] is None
    assert client(attached, "b").download_attachment(PROJECT, value["attachment_id"]).data == data

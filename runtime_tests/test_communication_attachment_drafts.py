"""Private draft refs over real PostgreSQL upload metadata and viewer bindings.

Draft saves never publish CAS content, pin an upload, or send Native input.
The attached fixture admits the existing platform store; pending refs need no
blob publication. Run only against the explicit disposable communication DB.
"""
from __future__ import annotations

import psycopg
import pytest

from runtime import communication_attachment_storage as attachments
from runtime import communication_client_storage as client_storage
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, IdempotencyConflict, RevisionConflict
from runtime.surface_config import CommunicationAttachmentSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_attachments import (
    PROJECT,
    associate,
    bind,
    client,
    declare,
    ready,
    reserve,
    row,
    upload,
)
from runtime_tests.test_communication_client_attachments import (
    attached as attached_fixture,
)
from runtime_tests.test_notification_continuity import shared_principal_clients

comm = comm_fixture
attached = attached_fixture
ADDRESS_A = "collaborator:project-alpha:local-slot"
ADDRESS_B = "collaborator:project-alpha:slot-b"


@pytest.fixture
def drafts(attached):
    with psycopg.connect(attached.dsn) as connection:
        client_storage.adopt_client_storage(connection)
    return attached


def view(f, first=ADDRESS_A, second=ADDRESS_B):
    return conversation_view_id(f.authority.tenant_id, PROJECT, first, second)


def save(service, conversation, refs, *, content="Unsent 汉字 🧭", revision=0, key="draft"):
    return service.update_draft(PROJECT, conversation, {"content": content, "attachment_refs": refs},
                                expected_revision=revision, client_request_id=key)


def private_counts(f):
    with psycopg.connect(f.dsn) as connection:
        return tuple(connection.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in
                     ("communication_client_drafts", "communication_client_write_keys"))


def public_rows(f):
    tables = ("communication_messages", "communication_replies", "delivery_messages", "delivery_receipts",
              "delivery_attempts", "communication_message_attachments", "inbox_messages")
    with psycopg.connect(f.dsn) as connection:
        return {name: connection.execute("SELECT to_jsonb(s) FROM " + name + " s ORDER BY to_jsonb(s)::text").fetchall()
                for name in tables}


def no_blob_io(*_args, **_kwargs):
    raise AssertionError("draft refs must not access CAS content")


def test_reserved_uploaded_and_ready_refs_keep_order_without_pin_or_message_effects(drafts, monkeypatch):
    service, conversation = client(drafts), view(drafts)
    pending = reserve(service, b"pending", key="reserved")
    staged = reserve(service, b"staged", key="staged")
    upload(service, staged, b"staged", key="staged-upload")
    finalized = ready(service, b"ready", key="ready")
    refs = [finalized["attachment_id"], pending["attachment_id"], staged["attachment_id"]]
    before = public_rows(drafts)
    originals = {identifier: row(drafts, identifier) for identifier in refs}
    monkeypatch.setattr(drafts.attachment_store, "put_bytes", no_blob_io)
    monkeypatch.setattr(drafts.attachment_store, "verify", no_blob_io)
    monkeypatch.setattr(drafts.attachment_store, "read", no_blob_io)

    saved = save(service, conversation, refs)
    assert saved["attachment_refs"] == refs and saved["content"] == "Unsent 汉字 🧭"
    assert service.draft(PROJECT, conversation) == saved
    deleted = service.delete_draft(PROJECT, conversation, expected_revision=1, client_request_id="delete")
    assert deleted["content"] == "" and deleted["attachment_refs"] == [] and deleted["revision"] == 2
    assert save(service, conversation, refs) == saved
    assert service.draft(PROJECT, conversation) == deleted
    assert {identifier: row(drafts, identifier) for identifier in refs} == originals
    assert all(not value["pinned"] for value in originals.values())
    assert public_rows(drafts) == before
    assert all(not driver.calls for driver in drafts.drivers.values())


def test_same_principal_opposite_slots_cannot_inherit_each_others_draft_uploads(drafts):
    shared_principal_clients(drafts)
    bind(drafts)
    first, second = client(drafts, "shared-1"), client(drafts, "shared-2")
    conversation = view(drafts, f"collaborator:{PROJECT}:shared-slot-1", f"collaborator:{PROJECT}:shared-slot-2")
    private_first = reserve(first, b"first", key="same-reserve")
    private_second = reserve(second, b"second", key="same-reserve")
    saved_first = save(first, conversation, [private_first["attachment_id"]], key="same-draft")
    with pytest.raises(CommunicationHttpError) as denied:
        save(second, conversation, [private_first["attachment_id"]], key="same-draft")
    assert denied.value.status_code == 404
    saved_second = save(second, conversation, [private_second["attachment_id"]], key="same-draft")
    assert first.draft(PROJECT, conversation) == saved_first
    assert second.draft(PROJECT, conversation) == saved_second
    assert saved_first["attachment_refs"] != saved_second["attachment_refs"]


def test_readable_incoming_shared_upload_does_not_grant_forwarding_ownership(drafts):
    owner, recipient = client(drafts), client(drafts, "b")
    value = ready(owner, b"explicitly shared bytes")
    associate(drafts, owner, value["attachment_id"])
    assert recipient.download_attachment(PROJECT, value["attachment_id"]).data == b"explicitly shared bytes"
    original = public_rows(drafts)
    with pytest.raises(CommunicationHttpError) as denied:
        save(recipient, view(drafts), [value["attachment_id"]])
    assert denied.value.status_code == 404 and private_counts(drafts) == (0, 0)
    assert public_rows(drafts) == original and row(drafts, value["attachment_id"])["pinned"]


def test_valid_attachment_from_other_project_cannot_be_saved_in_this_private_draft(drafts):
    service = client(drafts)
    tenant = drafts.authority.tenant_id
    address = "collaborator:project-other:other-slot"
    identity = attachments.AttachmentIdentity(tenant, "project-other", service._viewer_actor_ref("project-other", address),
                                               "draft-other-scope", address)
    with psycopg.connect(drafts.dsn) as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES ('draft-other-scope',%s,'active')", (tenant,))
        connection.execute("INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,name,context_manifest) "
                           "VALUES (%s,'project-other','draft-other-root','draft-other-scope','Other namespace','{}')", (tenant,))
        foreign = attachments.reserve_attachment(connection.cursor(), identity, declare(b"foreign"), "other-project")
    with pytest.raises(CommunicationHttpError) as denied:
        save(service, view(drafts), [foreign["attachment_id"]])
    assert denied.value.status_code == 404 and private_counts(drafts) == (0, 0)


@pytest.mark.parametrize("unavailable", ["expired", "rejected"])
def test_new_save_rejects_expired_or_rejected_upload_without_partial_private_state(drafts, unavailable):
    service = client(drafts)
    value = reserve(service, b"private pending")
    identifier = value["attachment_id"]
    with psycopg.connect(drafts.dsn) as connection:
        if unavailable == "expired":
            connection.execute("UPDATE communication_attachments SET expires_at=created_at+interval '1 microsecond',revision=revision+1 "
                               "WHERE attachment_id=%s", (identifier,))
        else:
            owner = service._transaction(PROJECT, "read_message", lambda bound, cur, root, _cmd:
                                          service._attachment_owner(bound, cur, root, PROJECT))
            attachments.reject_attachment(connection.cursor(), owner, identifier, expected_revision=1, request_namespace="rejected")
    with pytest.raises(CommunicationHttpError) as denied:
        save(service, view(drafts), [identifier])
    assert denied.value.status_code == (410 if unavailable == "expired" else 409)
    assert private_counts(drafts) == (0, 0)


def test_expired_ref_exact_retry_returns_original_receipt_after_later_delete_and_config_disable(drafts):
    service, conversation = client(drafts), view(drafts)
    value = reserve(service, b"will expire")
    refs = [value["attachment_id"]]
    saved = save(service, conversation, refs)
    deleted = service.delete_draft(PROJECT, conversation, expected_revision=1, client_request_id="delete")
    with psycopg.connect(drafts.dsn) as connection:
        connection.execute("UPDATE communication_attachments SET expires_at=created_at+interval '1 microsecond',revision=revision+1 "
                           "WHERE attachment_id=%s", (value["attachment_id"],))
    with pytest.raises(CommunicationHttpError) as expired:
        save(service, conversation, refs, revision=2, key="new-save")
    assert expired.value.status_code == 410
    service.authority._communication_attachments_enabled = False
    assert save(service, conversation, refs) == saved
    assert service.draft(PROJECT, conversation) == deleted
    assert private_counts(drafts) == (1, 2)
    with psycopg.connect(drafts.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'message.read' WHERE grant_ref=%s",
                           (service.project_service.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        save(service, conversation, refs)


@pytest.mark.parametrize("budget", ["count", "total", "file"])
def test_current_config_limits_use_actual_metadata_before_new_state_write(drafts, budget):
    service = client(drafts)
    first = reserve(service, b"12345", key="first")
    second = reserve(service, b"67890", key="second")
    drafts.attachment_settings = CommunicationAttachmentSettings(file_bytes=4 if budget == "file" else 8,
        message_count=1 if budget == "count" else 8, message_bytes=8,
        viewer_staging_bytes=32, project_staging_bytes=64)
    bind(drafts)
    refs = [first["attachment_id"]] if budget == "file" else [first["attachment_id"], second["attachment_id"]]
    with pytest.raises(CommunicationHttpError) as exceeded:
        save(service, view(drafts), refs)
    assert exceeded.value.status_code == 429 and private_counts(drafts) == (0, 0)
    assert not row(drafts, first["attachment_id"])["pinned"]


def test_duplicate_key_body_and_cas_conflicts_leave_original_text_refs_and_ledger(drafts):
    service, conversation = client(drafts), view(drafts)
    first = reserve(service, b"first", key="first")
    second = reserve(service, b"second", key="second")
    saved = save(service, conversation, [first["attachment_id"]])
    with pytest.raises(CommunicationHttpError) as duplicate:
        save(service, conversation, [first["attachment_id"], first["attachment_id"]], revision=1, key="duplicate")
    assert duplicate.value.status_code == 400
    with pytest.raises(IdempotencyConflict):
        save(service, conversation, [second["attachment_id"]])
    with pytest.raises(IdempotencyConflict):
        save(service, conversation, [first["attachment_id"]], content="Different unsent text")
    with pytest.raises(RevisionConflict):
        save(service, conversation, [second["attachment_id"]], key="stale-cas")
    assert service.draft(PROJECT, conversation) == saved and private_counts(drafts) == (1, 1)


def test_failed_receipt_rolls_back_draft_after_attachment_validation(drafts, monkeypatch):
    service, conversation = client(drafts), view(drafts)
    value = reserve(service, b"never pinned")
    original = row(drafts, value["attachment_id"])
    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("controlled private receipt failure")
    monkeypatch.setattr(client_storage, "_finish", fail_receipt)
    with pytest.raises(RuntimeError, match="controlled private receipt failure"):
        save(service, conversation, [value["attachment_id"]])
    assert private_counts(drafts) == (0, 0) and row(drafts, value["attachment_id"]) == original


def test_empty_legacy_draft_and_utf8_budget_work_with_feature_off_without_source_privilege(drafts, monkeypatch):
    service, conversation = client(drafts), view(drafts)
    value = reserve(service, b"metadata only")
    with psycopg.connect(drafts.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'source.read'-'artifact.read'-'artifact.write' WHERE grant_ref=%s",
                           (service.project_service.context.grant_ref,))
    monkeypatch.setattr(drafts.attachment_store, "put_bytes", no_blob_io)
    monkeypatch.setattr(drafts.attachment_store, "verify", no_blob_io)
    monkeypatch.setattr(drafts.attachment_store, "read", no_blob_io)
    saved = save(service, conversation, [value["attachment_id"]])
    with pytest.raises(AuthorizationDenied):
        service._transaction(PROJECT, "read_message", lambda bound, cur, _root, command:
                             bound._authorize(command, cur, "source.read", "local-scope"))
    service.authority._communication_attachments_enabled = False
    empty = save(service, conversation, [], revision=1, key="empty-legacy")
    assert empty["attachment_refs"] == [] and service.draft(PROJECT, conversation) == empty
    with pytest.raises(CommunicationHttpError) as disabled:
        save(service, conversation, [value["attachment_id"]], revision=2, key="disabled")
    assert disabled.value.code == "capability_unsupported"
    with pytest.raises(CommunicationHttpError) as oversized:
        save(service, conversation, [], content="字" * (client_storage.MAX_DRAFT_BYTES // 3 + 1), revision=2, key="too-large")
    assert oversized.value.status_code == 413
    assert save(service, conversation, [value["attachment_id"]]) == saved
    assert service.draft(PROJECT, conversation) == empty and private_counts(drafts) == (1, 2)

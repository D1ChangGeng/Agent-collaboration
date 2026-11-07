"""Actual shared-Core attachment sends; private CAS bytes remain outside Native.

Requests are explicit controlled fixture actors, not autonomous Agent/model
replies. All message, packet, dedup, pin and receipt observations are real PG.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Event

import psycopg
import pytest

import runtime.communication_client_attachments as attachment_facade
from runtime import communication_attachment_storage as storage
from runtime.artifacts import LocalArtifactStore, WindowsArtifactStore
from runtime.client_contracts import ClientContracts, ClientContractViolation
from runtime.communication_attachment_content import put_attachment_content
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_http import CommunicationHttpError
from runtime.communication_wait_ingress import adopt_wait_ingress
from runtime.delivery import DeliveryDispatcher, DeliveryRejected
from runtime.delivery_models import InvocationRequest, MessagePacket
from runtime.errors import IdempotencyConflict
from runtime.models import CommandEnvelope
from runtime_tests.test_communication import call
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_attachments import attached as attached_fixture
from runtime_tests.test_communication_client_attachments import (
    bind,
    client,
    declare,
    ready,
    reserve,
    row,
    upload,
)
from runtime_tests.test_delivery import command
from runtime_tests.test_notification_continuity import shared_principal_clients

comm, attached = comm_fixture, attached_fixture
PROJECT, PEER = "project-alpha", "collaborator:project-alpha:slot-b"
CORE_TABLES = ("communication_messages", "delivery_messages", "inbox_messages", "command_dedup", "domain_events", "operations", "outbox", "communication_message_attachments")
CONTRACTS = ClientContracts()


@pytest.fixture(scope="session", autouse=True)
def frozen_combined_source_fingerprints():
    import hashlib

    root = Path(__file__).resolve().parents[1]
    paths = {path for path in (root / "runtime").rglob("*") if path.is_file() and path.suffix in {".py", ".sql", ".json"}}
    paths.add(root / "docs/runtime/p2-mcp-tool-contract.json")
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename is not None:
            path = Path(filename).resolve()
            if path.is_relative_to(root / "runtime_tests") and path.suffix == ".py":
                paths.add(path)
    paths.update((root / "runtime_tests/fixtures").rglob("*.sql"))
    paths = sorted(paths)
    before = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    print(json.dumps({"fingerprint_scope": "All Runtime Python/SQL/JSON, actual tool catalog, imported test/fixture Python and fixture SQL; unrelated UI/SDK/docs excluded from this Python PG run.",
                      "source_fingerprints": before}, sort_keys=True))
    yield
    assert {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before, "frozen product or selected/reused test source changed during run"


@pytest.fixture
def sending(attached):
    with psycopg.connect(attached.dsn) as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
    return attached


def body(ids=None, **changes):
    value = {"to": PEER, "content": "Explicit message with verified attachment references", "activation": "message_only"}
    if ids is not None:
        value["attachment_refs"] = ids
    return value | changes


def counts(f):
    with psycopg.connect(f.dsn) as connection:
        return {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in CORE_TABLES}


def pinned(f):
    with psycopg.connect(f.dsn) as connection:
        return connection.execute("SELECT attachment_id,pinned,revision FROM communication_attachments ORDER BY attachment_id").fetchall()


def send(service, request, key="attachment-message"):
    value = service.send(PROJECT, request, client_request_id=key)
    CONTRACTS.validate("SendResponse", value)
    return value


def test_ready_metadata_freezes_in_packet_ordered_pins_and_recipient_read_download(sending):
    f, own, peer = sending, client(sending), client(sending, "b")
    first, second = ready(own, b"first bytes", key="first", name="first.txt"), ready(own, b"second bytes", key="second", name="second.txt")
    sent = send(own, body([second["attachment_id"], first["attachment_id"]]))
    references = sent["message"]["attachment_refs"]
    assert [item["attachment_id"] for item in references] == [second["attachment_id"], first["attachment_id"]]
    for expected, actual in zip((second, first), references, strict=True):
        assert actual == {key: expected[key] for key in ("attachment_id", "name", "media_type", "bytes", "sha256")}
    read = peer.read_message(PROJECT, sent["message"]["message_handle"])["message"]
    assert read["attachment_refs"] == references
    assert peer.attachment(PROJECT, first["attachment_id"])["state"] == "ready"
    assert peer.download_attachment(PROJECT, first["attachment_id"]).data == b"first bytes"
    with psycopg.connect(f.dsn) as connection:
        packet = connection.execute("SELECT packet_json FROM delivery_messages WHERE operation_id=%s", (sent["operation_ref"],)).fetchone()[0]
        assert packet["attachment_refs"] == references and packet["activation"] == "message_only"
        stored = connection.execute("SELECT attachment_id FROM communication_message_attachments WHERE message_id=%s ORDER BY position",
                                    (sent["message"]["message_handle"].split(":")[-1],)).fetchall()
        assert stored == [(second["attachment_id"],), (first["attachment_id"],)]
    assert row(f, first["attachment_id"])["pinned"] and row(f, first["attachment_id"])["expires_at"] is None
    assert sent["delivery"]["native"]["state"] == "not_requested"
    assert not any(driver.calls for driver in f.drivers.values())


@pytest.mark.parametrize("failure", ["missing", "nonready", "expired", "other_viewer", "count", "total"])
def test_failed_reference_sets_leave_no_message_dedup_or_partial_pin(sending, failure):
    f, own = sending, client(sending)
    first = ready(own, b"valid asset", key="valid")
    if failure == "missing":
        ids = [first["attachment_id"], "attachment-" + "0" * 32]
    elif failure == "nonready":
        ids = [first["attachment_id"], reserve(own, b"pending", key="pending")["attachment_id"]]
    elif failure == "expired":
        expired = ready(own, b"expired asset", key="expired")
        with psycopg.connect(f.dsn) as connection:
            connection.execute("UPDATE communication_attachments SET expires_at=created_at+interval '1 microsecond',revision=revision+1 WHERE attachment_id=%s", (expired["attachment_id"],))
            assert connection.execute("SELECT created_at<expires_at,expires_at<=clock_timestamp() FROM communication_attachments WHERE attachment_id=%s",
                                      (expired["attachment_id"],)).fetchone() == (True, True)
        ids = [first["attachment_id"], expired["attachment_id"]]
    elif failure == "other_viewer":
        ids = [first["attachment_id"], ready(client(f, "b"), b"private other viewer", key="private-b")["attachment_id"]]
    elif failure == "count":
        second = ready(own, b"second asset", key="second")
        f.attachment_settings = f.attachment_settings.model_copy(update={"message_count": 1})
        bind(f)
        ids = [first["attachment_id"], second["attachment_id"]]
    else:
        ids = [ready(own, b"a" * 180000, key="large-a")["attachment_id"], ready(own, b"b" * 180000, key="large-b")["attachment_id"]]
        f.attachment_settings = f.attachment_settings.model_copy(update={"message_bytes": f.attachment_settings.file_bytes})
        bind(f)
    before, pins = counts(f), pinned(f)
    with pytest.raises(CommunicationHttpError) as rejected:
        send(own, body(ids), key="failed-reference-set")
    if failure == "expired":
        assert rejected.value.status_code == 410
    else:
        assert rejected.value.status_code in {400, 404, 409, 429}
    assert rejected.value.effect_state == "none"
    assert counts(f) == before and pinned(f) == pins


def test_duplicate_after_pin_and_resource_revision_change_returns_same_operation_without_repin(sending):
    f, own = sending, client(sending)
    value = ready(own, b"deduplicated accepted blob")
    request = body([value["attachment_id"]])
    original = send(own, request, "same-message-key")
    first_pin = row(f, value["attachment_id"])
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE communication_attachments SET revision=revision+1 WHERE attachment_id=%s", (value["attachment_id"],))
        assert storage.expire_attachment_staging(connection, tenant_id=f.authority.tenant_id, project_id=PROJECT) == 0
    before = counts(f)
    repeated = send(own, request, "same-message-key")
    assert repeated["duplicate"] and repeated["operation_ref"] == original["operation_ref"]
    assert repeated["message"]["message_handle"] == original["message"]["message_handle"]
    assert repeated["message"]["attachment_refs"] == original["message"]["attachment_refs"]
    assert counts(f) == before
    assert row(f, value["attachment_id"])["revision"] == first_pin["revision"] + 1


def test_empty_refs_and_omitted_refs_share_old_message_key(sending):
    f, own = sending, client(sending)
    first = send(own, body(), "legacy-empty")
    before = counts(f)
    repeated = send(own, body([]), "legacy-empty")
    assert repeated["duplicate"] and repeated["operation_ref"] == first["operation_ref"]
    assert counts(f) == before
    with psycopg.connect(f.dsn) as connection:
        packet = connection.execute("SELECT packet_json FROM delivery_messages WHERE operation_id=%s", (first["operation_ref"],)).fetchone()[0]
        assert "attachment_refs" not in packet


def test_same_bytes_different_ids_and_attachment_order_remain_distinct_request_identity(sending):
    f, own = sending, client(sending)
    first, second = ready(own, b"same bytes", key="same-a"), ready(own, b"same bytes", key="same-b")
    assert first["sha256"] == second["sha256"] and first["attachment_id"] != second["attachment_id"]
    original = send(own, body([first["attachment_id"], second["attachment_id"]]), "ordered-key")
    before = counts(f)
    for ids in ([second["attachment_id"], first["attachment_id"]], [first["attachment_id"]], [second["attachment_id"]]):
        with pytest.raises(CommunicationHttpError) as conflict:
            send(own, body(ids), "ordered-key")
        assert conflict.value.code == "idempotency_conflict"
    assert counts(f) == before
    assert [item["attachment_id"] for item in original["message"]["attachment_refs"]] == [first["attachment_id"], second["attachment_id"]]


def test_recipient_can_download_but_cannot_forward_uploader_id_without_own_upload(sending):
    f, own, peer = sending, client(sending), client(sending, "b")
    value = ready(own, b"owner sharing policy")
    send(own, body([value["attachment_id"]]))
    assert peer.download_attachment(PROJECT, value["attachment_id"]).data == b"owner sharing policy"
    before = counts(f)
    with pytest.raises(CommunicationHttpError) as denied:
        send(peer, body([value["attachment_id"]], to="collaborator:project-alpha:slot-c"), "cannot-forward-id")
    assert denied.value.status_code == 404 and counts(f) == before
    uploaded = ready(peer, b"owner sharing policy", key="own-new-upload")
    assert uploaded["attachment_id"] != value["attachment_id"]
    assert send(peer, body([uploaded["attachment_id"]], to="collaborator:project-alpha:slot-c"), "own-reupload")["message"]["attachment_refs"][0]["attachment_id"] == uploaded["attachment_id"]


def test_same_principal_other_slot_cannot_send_private_uploader_id(sending):
    f = sending
    shared_principal_clients(f)
    bind(f)
    first, second = client(f, "shared-1"), client(f, "shared-2")
    value = ready(first, b"one actual viewer owns this", key="shared-private")
    before = counts(f)
    with pytest.raises(CommunicationHttpError) as denied:
        send(second, body([value["attachment_id"]]), "shared-principal-not-owner")
    assert denied.value.status_code == 404 and counts(f) == before
    assert not row(f, value["attachment_id"])["pinned"]


def test_ready_historical_scope_reference_cannot_cross_current_sender_scope(sending, tmp_path):
    f, own, data = sending, client(sending), b"historical scope-bound upload"
    scope = "attachment-old-scope-" + uuid.uuid4().hex
    current_owner = own._attachment_tx(PROJECT, lambda _b, _c, owner, _l, _cmd: owner)
    historical_owner = replace(current_owner, scope_id=scope)
    limits = f.attachment_settings.to_limits()
    declaration = declare(data)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO scopes VALUES (%s,%s,'{}','active')", (scope, f.authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) VALUES (%s,%s,%s,%s,'{}')", (f.authority.tenant_id, PROJECT, scope, scope))
        value = storage.reserve_attachment(connection.cursor(), historical_owner, declaration, "historical-reserve", limits=limits)
        lease = storage.begin_attachment_upload(connection.cursor(), historical_owner, value["attachment_id"], expected_revision=value["revision"], request_namespace="historical-begin", limits=limits)
        storage.append_attachment_chunk(connection.cursor(), historical_owner, value["attachment_id"], lease, 0, data)
        uploaded = storage.complete_attachment_upload(connection.cursor(), historical_owner, value["attachment_id"], lease, "historical-complete")
    root = tmp_path / "historical-private-cas"
    if os.name == "nt":
        from runtime_tests.test_windows_artifact_store import _private
        _private(root)
        backend = WindowsArtifactStore
    else:
        backend = LocalArtifactStore
    # Trusted storage fixture represents bytes accepted under a previous Scope;
    # it does not mint a Domain caller authorized for that historical Scope.
    with backend(root, scope, max_bytes=limits.file_bytes) as store:
        artifact = put_attachment_content(store, data, expected_scope=scope, declared_bytes=len(data),
                                          declared_sha256=declaration["sha256"], media_type="text/plain", max_bytes=limits.file_bytes)
        with psycopg.connect(f.dsn) as connection:
            storage.finish_attachment_ready(connection.cursor(), historical_owner, value["attachment_id"], lease, artifact,
                expected_revision=uploaded["revision"], request_namespace="historical-ready")
        before, pins = counts(f), pinned(f)
        with pytest.raises(CommunicationHttpError) as denied:
            send(own, body([value["attachment_id"]]), "cannot-cross-scope")
        assert denied.value.status_code == 404 and counts(f) == before and pinned(f) == pins


def test_sender_injection_and_revoked_artifact_read_reject_before_message_commit(sending):
    f, own = sending, client(sending)
    value = ready(own, b"current artifact permission")
    before = counts(f)
    with pytest.raises(ClientContractViolation):
        send(own, body([value["attachment_id"]], sender="collaborator:project-alpha:slot-b"), "forged-sender")
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'artifact.read' WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    with pytest.raises(CommunicationHttpError) as revoked:
        send(own, body([value["attachment_id"]]), "revoked-artifact-read")
    assert revoked.value.status_code == 403 and revoked.value.effect_state == "none"
    assert counts(f) == before and not row(f, value["attachment_id"])["pinned"]


def test_existing_cas_bytes_do_not_make_inflight_finalize_sendable(sending, monkeypatch):
    f, own, data = sending, client(sending), b"finalize admission race"
    value = reserve(own, data)
    upload(own, value, data)
    published, release = Event(), Event()
    original = attachment_facade.put_attachment_content

    def hold_after_cas(*args, **kwargs):
        reference = original(*args, **kwargs)
        published.set()
        assert release.wait(timeout=5)
        return reference

    monkeypatch.setattr(attachment_facade, "put_attachment_content", hold_after_cas)
    with ThreadPoolExecutor(max_workers=1) as pool:
        finalizer = pool.submit(own.finalize_attachment, PROJECT, value["attachment_id"],
            {"bytes": value["bytes"], "sha256": value["sha256"]}, client_request_id="finalizer-race")
        assert published.wait(timeout=5)
        before = counts(f)
        try:
            with pytest.raises(CommunicationHttpError) as not_ready:
                send(own, body([value["attachment_id"]]), "send-while-finalizing")
            assert not_ready.value.status_code == 409 and counts(f) == before
            with psycopg.connect(f.dsn) as connection:
                assert storage.expire_attachment_staging(connection, tenant_id=f.authority.tenant_id, project_id=PROJECT) == 0
        finally:
            release.set()
        assert finalizer.result(timeout=5)["state"] == "ready"
    assert send(own, body([value["attachment_id"]]), "send-while-finalizing")["message"]["attachment_refs"]


def test_invoke_retains_real_inbox_with_unsupported_native_and_zero_dispatch(sending):
    f, own = sending, client(sending)
    value = ready(own, b"retained attachment")
    sent = send(own, body([value["attachment_id"]], activation="invoke"), "unsupported-native")
    assert sent["delivery"]["accepted_by_authority"] and sent["delivery"]["target_inbox_committed"]
    assert sent["delivery"]["native"]["state"] == "unsupported"
    identifier = sent["message"]["message_handle"].split(":")[-1]
    with psycopg.connect(f.dsn) as connection:
        source = connection.execute("SELECT state,last_error,packet_json->>'activation' FROM delivery_messages WHERE message_id=%s", (identifier,)).fetchone()
        assert source == ("blocked", "native_attachment_delivery_unsupported", "invoke")
        assert connection.execute("SELECT layer,evidence_json->>'source' FROM delivery_receipts WHERE message_id=%s AND layer='target_inbox_committed'", (identifier,)).fetchone() == ("target_inbox_committed", "authority_inbox")
        assert connection.execute("SELECT 1 FROM delivery_receipts WHERE message_id=%s AND layer IN ('runtime_dispatched','runtime_acknowledged','response_received')", (identifier,)).fetchone() is None
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
    assert call(f, "b", "read_message", handle=sent["message"]["message_handle"])["data"]["attachment_refs"] == sent["message"]["attachment_refs"]
    assert not any(driver.calls for driver in f.drivers.values())


def test_invoke_permission_denial_is_not_bypassed_by_native_unsupported_hold(sending):
    f, own = sending, client(sending)
    value = ready(own, b"invoke permission")
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'runtime.invoke' WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    before = counts(f)
    with pytest.raises(CommunicationHttpError) as denied:
        send(own, body([value["attachment_id"]], activation="invoke"), "invoke-denied")
    assert denied.value.status_code == 403 and counts(f) == before
    assert not row(f, value["attachment_id"])["pinned"]


def test_active_wait_result_does_not_overwrite_attachment_native_hold(sending):
    f, own = sending, client(sending)
    with psycopg.connect(f.dsn) as connection:
        adopt_wait_ingress(connection)
    for source in f.clients.values():
        source.service.service.authority._wait_ingress_recovery_enabled = True
    request = call(f, "b", "send_message", to="collaborator:project-alpha:local-slot", content="Explicit request for attachment", activation="message_only", client_request_id="wait-original")["data"]
    value = ready(own, b"explicit attachment reply")

    def wait_for_reply():
        return call(f, "b", "wait_for_response", handles=[request["message_handle"]], timeout_seconds=4)

    with ThreadPoolExecutor(max_workers=1) as pool:
        waiter = pool.submit(wait_for_reply)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with psycopg.connect(f.dsn) as connection:
                active = connection.execute("SELECT 1 FROM communication_waits WHERE request_id=%s AND expires_at>clock_timestamp()", (request["message_id"],)).fetchone()
            if active:
                break
            time.sleep(0.01)
        assert active
        reply = send(own, body([value["attachment_id"]], activation="invoke", reply_to=[request["message_handle"]]), "wait-reply")
        assert waiter.result(timeout=5)["state"] == "satisfied"
    identifier = reply["message"]["message_handle"].split(":")[-1]
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT state,last_error FROM delivery_messages WHERE message_id=%s", (identifier,)).fetchone() == ("blocked", "native_attachment_delivery_unsupported")
        assert connection.execute("SELECT 1 FROM communication_wait_ingress WHERE message_id=%s", (identifier,)).fetchone() is None
    assert not any(driver.calls for driver in f.drivers.values())


def test_lowlevel_packet_metadata_is_authoritative_and_canonical_dedup_covers_it(sending):
    f, own = sending, client(sending)
    value = ready(own, b"typed packet metadata")
    sent = send(own, body([value["attachment_id"]]), "canonical-metadata")
    with psycopg.connect(f.dsn) as connection:
        packet_json, command_json = connection.execute("SELECT packet_json,command_json FROM delivery_messages WHERE operation_id=%s", (sent["operation_ref"],)).fetchone()
    packet = MessagePacket.model_validate_json(json.dumps(packet_json))
    changed = packet.model_copy(update={"attachment_refs": tuple(reference.model_copy(update={"name": "forged.txt"}) for reference in packet.attachment_refs)})
    before = counts(f)
    original_command = CommandEnvelope.model_validate_json(json.dumps(command_json))
    with pytest.raises(IdempotencyConflict):
        f.dispatcher.service.send_message(original_command, changed, endpoint_id=None, binding_revision=None)
    forged_command = command(f.authority, "message.send", "message-" + uuid.uuid4().hex,
        payload={"schema_version": "acs-message/1", "communication_project_id": PROJECT})
    with pytest.raises(DeliveryRejected, match="attachment_packet_identity_changed"):
        f.dispatcher.service.send_message(forged_command, changed, endpoint_id=None, binding_revision=None)
    assert counts(f) == before


def test_recovered_queued_attachment_keeps_inbox_and_never_requests_resolver_fallback(sending, monkeypatch):
    f, own = sending, client(sending)
    value = ready(own, b"legacy queued attachment guard")
    sent = send(own, body([value["attachment_id"]], activation="invoke"), "queued-recovery-guard")
    identifier = sent["message"]["message_handle"].split(":")[-1]
    with psycopg.connect(f.dsn) as connection:
        inbox_receipt = connection.execute("SELECT receipt_id,evidence_json FROM delivery_receipts WHERE message_id=%s AND layer='target_inbox_committed'", (identifier,)).fetchone()
        connection.execute("UPDATE delivery_messages SET state='queued',last_error=NULL WHERE message_id=%s", (identifier,))
    requested = []

    def must_not_resolve(*_args, **_kwargs):
        requested.append(True)
        raise AssertionError("unsupported attachments must not request resession or fallback")

    monkeypatch.setattr(f.dispatcher.service, "endpoint_resolver", must_not_resolve)
    result = DeliveryDispatcher(f.dispatcher.service).dispatch({"tenant_id": f.authority.tenant_id,
        "message_id": identifier, "operation_id": sent["operation_ref"]})
    assert result["status"] == "blocked" and requested == []
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT state,last_error FROM delivery_messages WHERE message_id=%s", (identifier,)).fetchone() == ("blocked", "native_attachment_delivery_unsupported")
        assert connection.execute("SELECT receipt_id,evidence_json FROM delivery_receipts WHERE message_id=%s AND layer='target_inbox_committed'", (identifier,)).fetchone() == inbox_receipt
        assert connection.execute("SELECT 1 FROM delivery_receipts WHERE message_id=%s AND layer IN ('runtime_dispatched','runtime_acknowledged','response_received')", (identifier,)).fetchone() is None
    endpoint = f.authority._delivery_endpoints["endpoint-b"]
    with closing(endpoint.journal._connect()) as journal:
        assert journal.execute("SELECT 1 FROM delivery_invocations WHERE operation_id=?", (sent["operation_ref"],)).fetchone() is None
    assert not any(driver.calls for driver in f.drivers.values())


def test_existing_domain_dispatch_fact_is_preserved_as_uncertain_without_retrying_native(sending, monkeypatch):
    f, own = sending, client(sending)
    value = ready(own, b"possible legacy dispatch evidence")
    sent = send(own, body([value["attachment_id"]], activation="invoke"), "possible-dispatch-guard")
    identifier = sent["message"]["message_handle"].split(":")[-1]
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET state='queued',last_error=NULL WHERE message_id=%s", (identifier,))
    recorded = []

    class ExistingPossibleDispatch(DeliveryDispatcher):
        def after_claim(self, identity):
            # Established fault seam: retain the original prepared invocation's
            # actual identities in a durable Core marker. This is controlled
            # possible-effect evidence, not a claim that a Driver was invoked.
            with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE message_id=%s", (identifier,))
                message = cursor.fetchone()[0]
                cursor.execute("SELECT invocation_json FROM delivery_attempts WHERE message_id=%s ORDER BY ordinal DESC LIMIT 1", (identifier,))
                invocation = InvocationRequest.model_validate_json(json.dumps(cursor.fetchone()[0]))
                evidence = {"source": "controlled_possible_dispatch_fixture", "dispatch_id": invocation.dispatch_id,
                            "invocation_id": invocation.invocation_id}
                self._record_receipt(cursor, message, invocation.runtime_dispatched_receipt_id, "runtime_dispatched", evidence,
                                     attempt_id=invocation.attempt_id, dispatch_id=invocation.dispatch_id)
                cursor.execute("UPDATE delivery_attempts SET status='runtime_dispatched' WHERE message_id=%s AND attempt_id=%s", (identifier, invocation.attempt_id))
                cursor.execute("UPDATE delivery_messages SET activation_node_id=%s,activation_machine_id=%s,activation_dispatch_id=%s,activation_receipt_id=%s WHERE message_id=%s",
                    (invocation.envelope.node_id, invocation.envelope.machine_id, invocation.dispatch_id, invocation.runtime_dispatched_receipt_id, identifier))
                recorded.append((invocation.runtime_dispatched_receipt_id, evidence))

    requested = []
    monkeypatch.setattr(f.dispatcher.service, "endpoint_resolver", lambda *_args, **_kwargs: requested.append(True))
    identity = {"tenant_id": f.authority.tenant_id, "message_id": identifier, "operation_id": sent["operation_ref"]}
    result = ExistingPossibleDispatch(f.dispatcher.service).dispatch(identity)
    assert result["status"] == "uncertain" and requested == [] and len(recorded) == 1
    assert DeliveryDispatcher(f.dispatcher.service).dispatch(identity)["status"] == "uncertain"
    with psycopg.connect(f.dsn) as connection:
        source = connection.execute("SELECT state,last_error FROM delivery_messages WHERE message_id=%s", (identifier,)).fetchone()
        assert source[0] == "uncertain" and source[1] != "native_attachment_delivery_unsupported"
        assert connection.execute("SELECT receipt_id,evidence_json FROM delivery_receipts WHERE message_id=%s AND layer='runtime_dispatched'", (identifier,)).fetchone() == recorded[0]
        assert connection.execute("SELECT 1 FROM delivery_receipts WHERE message_id=%s AND layer='runtime_acknowledged'", (identifier,)).fetchone() is None
    assert not any(driver.calls for driver in f.drivers.values())

"""Actual SQLite and signed-protocol attachment guards; no Native/model inputs.

Drivers/readbacks are controlled fixtures. The signed receiver fixture admits
only its own temporary SQLite file, independently of deployment path admission;
actual signature, nonce, boot, identity and durable-marker logic remain in use.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

import runtime.receiver as receiver_module
from runtime.codex_driver import AuthorizedOperation, DriverJournal, OutcomeUncertain
from runtime.delivery_models import (
    DeliveryEnvelope,
    InvocationObservation,
    MessageAttachmentRef,
    MessagePacket,
)
from runtime.delivery_node import (
    NATIVE_ATTACHMENT_UNSUPPORTED,
    InvocationPreCallRejected,
    LocalNodeEndpoint,
    invocation_for,
)
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.receiver import ReceiverLedger, ReceiverRejected, ReceiverService
from runtime.receiver_crypto import canonical, sha256, sign
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge, RemoteNodeEndpointAdapter
from runtime.receiver_models import (
    DispatchBody,
    PrepareBody,
    ReadbackBody,
    ReadinessBody,
    RecoveryBody,
)
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime_tests import test_receiver_connection_clock as clock_fixture


class ControlledDriver:
    evidence_class = "fixture_callback"

    def __init__(self):
        self.prepares, self.inputs = [], []

    def prepare(self, invocation):
        self.prepares.append(invocation)
        return invocation

    def invoke(self, invocation):
        self.inputs.append(invocation)
        return InvocationObservation(invocation_id=invocation.invocation_id, dispatch_id=invocation.dispatch_id,
            runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id, native_dispatch_ref="fixture:dispatch", native_ack_ref="fixture:ack")


def packet(*, attached=True, activation="invoke", scope="scope", slot="slot"):
    refs = (MessageAttachmentRef(attachment_id="attachment-" + "a" * 32, name="fixture.bin", media_type="application/octet-stream",
                                 bytes=3, sha256="a" * 64),) if attached else ()
    return MessagePacket(project_id="p", sender="collaborator:p:a", recipient="collaborator:p:" + slot,
        content="Do not submit this text without its attachment.", target_scope_id=scope, target_agent_slot_id=slot,
        activation=activation, attachment_refs=refs)


def envelope(node=None, *, attached=True, activation="invoke"):
    return DeliveryEnvelope(tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        principal_ref="agent:a", grant_ref="grant:a", message_id="message", command_id="command", operation_id="operation",
        endpoint_id="endpoint", binding_revision=1, machine_id=node.machine_id if node else "machine",
        node_id=node.node_id if node else "node", boot_incarnation=node.boot_incarnation if node else "boot",
        accepted_state_digest="c" * 64, packet=packet(attached=attached, activation=activation))


def local(tmp_path, *, attached=True, activation="invoke"):
    driver = ControlledDriver()
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / "node.sqlite"), "scope", "slot", driver)
    value = envelope(endpoint.identity, attached=attached, activation=activation)
    return endpoint, driver, value, invocation_for(value, "attempt")


def local_marker(invocation, source):
    return {"invocation_id": invocation.invocation_id, "attempt_id": invocation.attempt_id, "dispatch_id": invocation.dispatch_id,
        "receipt_id": invocation.runtime_dispatched_receipt_id, "operation_id": invocation.operation_id, "command_id": invocation.command_id,
        "message_id": invocation.message_id, "envelope_digest": invocation.envelope_digest,
        "logical_payload_digest": invocation.logical_payload_digest, "selection_digest": invocation.selection_digest,
        "accepted_revision": invocation.accepted_revision, "accepted_state_digest": invocation.accepted_state_digest, "source": source}


def seed_local_history(endpoint, value, invocation, state):
    # Explicit persisted old-version history, not a new dispatch permission.
    endpoint._commit_inbox(value, lambda: value)
    with endpoint.journal._transaction() as connection:
        connection.execute("INSERT INTO delivery_invocations VALUES (?,?,?,?,?,?,NULL)",
            (invocation.operation_id, invocation.invocation_id, invocation.dispatch_id,
             invocation.runtime_dispatched_receipt_id, invocation.model_dump_json(), state))
        if state != "prepared":
            endpoint._receipt(connection, value, "runtime_dispatched", local_marker(invocation, endpoint.driver.evidence_class),
                              receipt_id=invocation.runtime_dispatched_receipt_id)
        if state == "acknowledged":
            endpoint._receipt(connection, value, "runtime_acknowledged", {"invocation_id": invocation.invocation_id,
                "dispatch_id": invocation.dispatch_id, "dispatch_receipt_id": invocation.runtime_dispatched_receipt_id,
                "native_ack_ref": "fixture:historical-ack", "native_dispatch_ref": "fixture:historical-dispatch", "source": endpoint.driver.evidence_class})


def test_local_attachment_message_commits_actual_inbox_and_rejects_before_any_driver_or_marker(tmp_path):
    endpoint, driver, value, invocation = local(tmp_path)
    markers = []
    for _repeat in range(2):
        with pytest.raises(InvocationPreCallRejected, match=NATIVE_ATTACHMENT_UNSUPPORTED):
            endpoint.deliver(value, lambda: value, invocation, lambda *_args: markers.append(True), lambda _invocation: False)
    message = endpoint.journal.get_message(value.message_id)
    assert json.loads(message.payload_json)["value"]["packet"]["attachment_refs"][0]["attachment_id"] == packet().attachment_refs[0].attachment_id
    assert value.packet.activation == "invoke" and driver.prepares == driver.inputs == markers == []
    with closing(endpoint.journal._connect()) as connection:
        assert connection.execute("SELECT count(*) FROM delivery_invocations").fetchone()[0] == 0
    assert {receipt.layer for receipt in endpoint.journal.receipts(value.operation_id)} == {"accepted_by_authority", "target_inbox_committed"}


@pytest.mark.parametrize("attached,activation", [(True, "message_only"), (False, "message_only"), (False, "invoke")])
def test_plain_and_message_only_packets_keep_their_existing_delivery_behavior(tmp_path, attached, activation):
    endpoint, driver, value, invocation = local(tmp_path, attached=attached, activation=activation)
    markers = []
    result = endpoint.deliver(value, lambda: value, invocation, lambda *_args: markers.append(True))
    assert result["status"] == "delivered" and value.packet.activation == activation
    assert len(driver.inputs) == len(markers) == (1 if activation == "invoke" else 0)


@pytest.mark.parametrize("state", ["acknowledged", "uncertain"])
def test_existing_node_ack_or_possible_input_is_preserved_without_reinvocation(tmp_path, state):
    endpoint, driver, value, invocation = local(tmp_path)
    seed_local_history(endpoint, value, invocation, state)
    before = endpoint.journal.receipts(value.operation_id)
    result = endpoint.deliver(value, lambda: value, invocation, lambda *_args: pytest.fail("historical invocation marked again"))
    assert result["status"] == ("delivered" if state == "acknowledged" else "uncertain")
    reconciled = endpoint.reconcile_delivery(invocation)
    assert reconciled["status"] == result["status"]
    assert endpoint.journal.receipts(value.operation_id) == before and driver.prepares == driver.inputs == []


@pytest.mark.parametrize("domain_marker", [True, None])
def test_domain_marker_or_unavailable_marker_is_not_recast_as_known_no_effect(tmp_path, domain_marker):
    endpoint, driver, value, invocation = local(tmp_path)
    seed_local_history(endpoint, value, invocation, "prepared")
    result = endpoint.deliver(value, lambda: value, invocation, lambda *_args: pytest.fail("Domain marker recreated"), lambda _invocation: domain_marker)
    assert result["status"] == "uncertain" and driver.prepares == driver.inputs == []


@pytest.mark.parametrize("entry", ["prompt", "prepare", "invoke"])
def test_direct_native_adapter_entry_rejects_before_accessing_driver_or_journal(entry):
    adapter = object.__new__(NativeDeliveryAdapter)
    invocation = invocation_for(envelope(), "attempt")
    if entry == "prompt":
        call = lambda: adapter.prompt(invocation)
    elif entry == "prepare":
        call = lambda: adapter.prepare(invocation)
    else:
        call = lambda: adapter.invoke(invocation, on_dispatch=lambda: pytest.fail("native dispatch boundary entered"))
    with pytest.raises(InvocationPreCallRejected, match=NATIVE_ATTACHMENT_UNSUPPORTED):
        call()


@pytest.mark.parametrize("state", ["acknowledged", "uncertain"])
def test_pure_native_reconciliation_preserves_old_exact_ack_or_unknown_effect(tmp_path, state):
    invocation = invocation_for(envelope(), "attempt")
    operation = AuthorizedOperation(invocation.invocation_id, invocation.command_id, invocation.message_id, "fixture:grant", None)
    journal = DriverJournal(tmp_path / "driver.sqlite")
    binding = {"node_id": "node", "node_boot_id": "boot", "agent_slot_id": "slot", "revision": 1}
    journal.begin(operation, "fixture:binding", "invoke", {"text": "Explicit old-version text-only input fixture."})
    receipt = {"receipt_layer": "runtime_acknowledged", "operation_id": operation.operation_id, "command_id": operation.command_id,
        "message_id": operation.message_id, "binding_id": "fixture:binding", "binding": binding, "turn_id": "fixture:old-turn"}
    journal.finish(operation.operation_id, state, receipt if state == "acknowledged" else {})
    readonly = []

    def reconcile(*_args):
        readonly.append(True)
        raise OutcomeUncertain("controlled missing Native readback")

    adapter = object.__new__(NativeDeliveryAdapter)
    adapter._binding_id, adapter._binding, adapter._journal = "fixture:binding", binding, journal
    adapter.driver = SimpleNamespace(_lock=threading.RLock(), thread_id="fixture:session", reconcile=reconcile)
    adapter.observation_operation = lambda _invocation: operation
    adapter._check_binding = lambda: None
    before = journal.read(operation.operation_id)
    result = adapter.reconcile_input(invocation)
    assert result.outcome == ("accepted" if state == "acknowledged" else "unknown") and result.effect_possible
    assert journal.read(operation.operation_id) == before
    assert len(readonly) == (0 if state == "acknowledged" else 1)


class FixtureLedger(ReceiverLedger):
    """Actual receiver tables/transactions; only temporary path admission differs."""

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection


@pytest.fixture
def signed(tmp_path, monkeypatch):
    temporal = clock_fixture.temporal.__wrapped__()

    def file_identity(path):
        info = os.stat(path)
        return info.st_dev, info.st_ino

    def create(path):
        path.touch()
        return file_identity(path)

    def admit(path, *, private):
        assert private and path == tmp_path / "signed.sqlite"
        return os.open(path, os.O_RDWR), file_identity(path)

    monkeypatch.setattr(receiver_module, "ensure_private_database", create)
    monkeypatch.setattr(receiver_module, "open_validated_file", admit)
    ledger = FixtureLedger(tmp_path / "signed.sqlite")
    service = object.__new__(ReceiverService)
    service.config, service.binding, service.clock = temporal.config, temporal.config.binding, temporal.time.clock(temporal.config)
    service.node_signing_key, service.authorize_current, service.ledger = temporal.node_key, lambda _admission: True, ledger
    service.claim_boot("boot", 1)
    temporal.service, temporal.ledger = service, ledger
    yield temporal
    ledger.close()


def preparation(f, *, attached=True):
    value = envelope(attached=attached)
    invocation = invocation_for(value, "attempt")
    selection = RemoteNodeEndpointAdapter._selection(invocation)
    body = PrepareBody(envelope=value.model_dump(mode="json"), invocation=invocation.model_dump(mode="json"), selection=selection)
    identity = DeliveryIdentity(invocation.message_id, invocation.command_id, invocation.operation_id, invocation.attempt_id,
        invocation.dispatch_id, invocation.accepted_revision, invocation.accepted_state_digest, invocation.envelope_digest,
        invocation.selection_digest, sha256(invocation.model_dump(mode="json")), f.time.authority() + timedelta(minutes=1))
    factory = AdmissionFactory(f.config, f.authority_key, identity, clock=f.service.clock)
    request = factory.request("delivery.prepare", body)
    receipt = f.service.prepare(request)
    return SimpleNamespace(envelope=value, invocation=invocation, body=body, identity=identity, factory=factory, request=request, receipt=receipt)


def test_signed_dispatch_and_readiness_refuse_attachments_before_local_marker_or_probe(signed):
    f, calls = signed, []
    prepared = preparation(f)
    readiness = prepared.factory.request("delivery.readiness", ReadinessBody(prepare_request_id=prepared.request.admission.request_id))
    observed = f.service.readiness(readiness, lambda _admission: pytest.fail("unsupported attachment probed Native readiness"))
    assert observed.receipt.evidence["reason_code"] == NATIVE_ATTACHMENT_UNSUPPORTED
    dispatch = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="fixture:domain-marker"))
    result = f.service.dispatch(dispatch, lambda _admission: calls.append(True) or {}, after_marker=lambda: pytest.fail("unsupported dispatch marked"))
    assert result.receipt.state == "blocked" and result.receipt.evidence["reason"] == NATIVE_ATTACHMENT_UNSUPPORTED
    assert f.service.dispatch(dispatch, lambda _admission: pytest.fail("blocked request reinvoked")) == result
    with closing(f.ledger.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM native_calls").fetchone()[0] == 0
    assert calls == []


def test_signed_plain_message_dispatch_still_uses_exactly_one_input_and_marker(signed):
    prepared = preparation(signed, attached=False)
    dispatch = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker"))
    calls = []
    result = signed.service.dispatch(dispatch, lambda _admission: calls.append(True) or {"native_ack_ref": "fixture:ack"})
    assert result.receipt.state == "runtime_acknowledged" and calls == [True]
    assert signed.service.dispatch(dispatch, lambda _admission: pytest.fail("plain replay reinvoked")) == result


def test_signed_forgery_is_rejected_before_attachment_policy_or_effect(signed):
    prepared = preparation(signed)
    request = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker"))
    with pytest.raises(ValueError):
        signed.service.dispatch(request.model_copy(update={"signature": "0" * 128}), lambda _admission: pytest.fail("forged request invoked"))


def corrupt_preparation(f, prepared, kind):
    with f.ledger.transaction() as connection:
        if kind == "drop_refs":
            body = json.loads(canonical(prepared.request.body))
            body["envelope"]["packet"].pop("attachment_refs")
            body["invocation"]["envelope"]["packet"].pop("attachment_refs")
            connection.execute("UPDATE receiver_requests SET body_json=? WHERE request_id=?", (canonical(body).decode(), prepared.request.admission.request_id))
        elif kind == "body_sha":
            connection.execute("UPDATE receiver_requests SET body_sha256=? WHERE request_id=?", ("0" * 64, prepared.request.admission.request_id))
        else:
            original = prepared.request.model_dump(mode="json")
            original["body"]["envelope"]["packet"]["content"] = "corrupt independent signed-request copy"
            connection.execute("UPDATE receiver_requests SET signed_request_json=? WHERE request_id=?", (canonical(original).decode(), prepared.request.admission.request_id))


@pytest.mark.parametrize("corruption", ["drop_refs", "body_sha", "signed_copy"])
def test_corrupt_mutable_preparation_cannot_hide_attachments_before_fresh_marker(signed, corruption):
    prepared = preparation(signed)
    corrupt_preparation(signed, prepared, corruption)
    request = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker"))
    with pytest.raises(ReceiverRejected, match="prepared signed request integrity rejected"):
        signed.service.dispatch(request, lambda _admission: pytest.fail("corrupt preparation invoked"),
                                after_marker=lambda: pytest.fail("corrupt preparation marked"))
    with closing(signed.ledger.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM native_calls").fetchone()[0] == 0


def test_direct_bridge_rejects_corrupt_body_copy_before_driver_access(signed):
    prepared = preparation(signed)
    corrupt_preparation(signed, prepared, "drop_refs")
    bridge = ReceiverNativeDeliveryBridge(str(signed.ledger.path), object(), read_domain_marker=lambda _inv: pytest.fail("corrupt bridge read marker"))
    with pytest.raises(ReceiverRejected, match="prepared signed request integrity rejected"):
        bridge(prepared.request.admission)


@pytest.mark.parametrize("state", ["runtime_acknowledged", "uncertain"])
def test_signed_historical_ack_and_unknown_readback_are_not_downgraded_by_unsupported_policy(signed, state):
    prepared = preparation(signed)
    request = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker"))
    _body, request_hash = signed.service._verify(request)
    with signed.ledger.transaction() as connection:
        original = signed.service._insert(connection, request, request_hash, state, True, {"source": "fixture:historical-native"})
    assert signed.service.dispatch(request, lambda _admission: pytest.fail("historical request reinvoked")) == original
    read = prepared.factory.request("delivery.readback", ReadbackBody(operation_id=request.admission.operation_id, dispatch_id=request.admission.dispatch_id))
    result = signed.service.readback(read)
    assert result.receipt.evidence["stored_state"] == state
    with closing(signed.ledger.connect()) as connection:
        assert connection.execute("SELECT receipt_json FROM receiver_requests WHERE request_id=?", (request.admission.request_id,)).fetchone()[0] == original.model_dump_json()


@pytest.mark.parametrize("state", ["runtime_acknowledged", "uncertain"])
def test_corrupt_prepare_does_not_erase_already_recorded_ack_or_unknown(signed, state):
    prepared = preparation(signed)
    request = prepared.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker"))
    _body, request_hash = signed.service._verify(request)
    with signed.ledger.transaction() as connection:
        original = signed.service._insert(connection, request, request_hash, state, True, {"source": "fixture:historical-effect"})
    corrupt_preparation(signed, prepared, "drop_refs")
    assert signed.service.dispatch(request, lambda _admission: pytest.fail("historical marker reinvoked")) == original
    with closing(signed.ledger.connect()) as connection:
        row = connection.execute("SELECT state,local_dispatch_marker,receipt_json FROM receiver_requests WHERE request_id=?", (request.admission.request_id,)).fetchone()
    assert tuple(row) == (state, 1, original.model_dump_json())


def test_signed_new_boot_recovery_is_blocked_before_new_marker_or_input(signed):
    f = signed
    prepared = preparation(f)
    registration = f.config.binding.registration.model_copy(update={"boot_incarnation": "boot-2", "endpoint_revision": 2, "runtime_revision": 2})
    binding = f.config.binding.model_copy(update={"registration": registration, "registration_signature": sign(f.node_key, registration)})
    current = replace(f.config, binding=binding, expected_boot_incarnation="boot-2", journal_generation=2, old_boot_isolation_ref="fixture:isolation")
    f.service.config, f.service.binding, f.service.clock = current, binding, f.time.clock(current)
    f.service.claim_boot("boot-2", 2, old_boot_isolation_ref="fixture:isolation")
    factory = AdmissionFactory(current, f.authority_key, prepared.identity, clock=f.service.clock)
    request = factory.request("delivery.recover", RecoveryBody(prepare_request_id=prepared.request.admission.request_id, marker_receipt_id="marker",
        old_boot_incarnation="boot", new_boot_incarnation="boot-2", journal_generation=2, old_boot_isolation_ref="fixture:isolation",
        old_endpoint_revision=1, new_endpoint_revision=2, old_runtime_revision=1, new_runtime_revision=2),
        boot_incarnation="boot-2", journal_generation=2)
    result = f.service.recover(request, lambda _admission: pytest.fail("attachment recovery invoked"), after_marker=lambda: pytest.fail("attachment recovery marked"))
    assert result.receipt.state == "blocked" and result.receipt.evidence["reason"] == NATIVE_ATTACHMENT_UNSUPPORTED
    with closing(f.ledger.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == 0


@pytest.mark.parametrize("entry", ["invoke", "readiness"])
def test_bridge_direct_entries_cannot_bypass_attachment_guard(signed, entry):
    prepared = preparation(signed)
    adapter = SimpleNamespace(prepare=lambda _inv: pytest.fail("bridge prepared unsupported input"),
        invoke=lambda *_args, **_kwargs: pytest.fail("bridge invoked unsupported input"), readiness=lambda _inv: pytest.fail("bridge readied unsupported input"))
    bridge = ReceiverNativeDeliveryBridge(str(signed.ledger.path), adapter, read_domain_marker=lambda _inv: pytest.fail("bridge read marker"))
    with pytest.raises(InvocationPreCallRejected, match=NATIVE_ATTACHMENT_UNSUPPORTED):
        (bridge if entry == "invoke" else bridge.readiness)(prepared.request.admission)


def test_remote_sender_retains_real_preparation_but_never_creates_domain_dispatch_marker(signed):
    prepared = preparation(signed)
    endpoint = object.__new__(RemoteNodeEndpointAdapter)
    endpoint.store = SimpleNamespace(dispatch_admission=lambda _operation: None)

    def issue(invocation, purpose, body):
        assert invocation == prepared.invocation and purpose == "delivery.prepare" and body == prepared.body
        return prepared.request

    endpoint._issue, endpoint._send = issue, signed.service.prepare
    with pytest.raises(InvocationPreCallRejected, match=NATIVE_ATTACHMENT_UNSUPPORTED):
        endpoint.deliver(prepared.envelope, lambda: prepared.envelope, prepared.invocation,
            lambda *_args: pytest.fail("unsupported remote delivery marked Domain"), lambda _invocation: False)
    with closing(signed.ledger.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE purpose='delivery.prepare'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == 0


def test_remote_sender_with_existing_possible_dispatch_only_observes_original_status(signed):
    prepared = preparation(signed)
    endpoint = object.__new__(RemoteNodeEndpointAdapter)
    endpoint.store = SimpleNamespace(dispatch_admission=lambda _operation: object())
    observed = {"status": "uncertain", "receipts": [{"layer": "target_inbox_committed", "evidence": {"source": "fixture:old-receiver"}}]}
    endpoint.inspect_delivery = lambda operation, status: observed
    result = endpoint.deliver(prepared.envelope, lambda: prepared.envelope, prepared.invocation,
        lambda *_args: pytest.fail("possible remote input marked again"), lambda _invocation: True)
    assert result is observed


def test_remote_recovery_direct_entry_refuses_before_admission_or_domain_marker(signed):
    prepared = preparation(signed)
    registration = signed.config.binding.registration.model_copy(update={"boot_incarnation": "boot-2", "endpoint_revision": 2, "runtime_revision": 2})
    binding = signed.config.binding.model_copy(update={"registration": registration, "registration_signature": sign(signed.node_key, registration)})
    endpoint = object.__new__(RemoteNodeEndpointAdapter)
    endpoint.config = replace(signed.config, binding=binding, expected_boot_incarnation="boot-2", journal_generation=2, old_boot_isolation_ref="fixture:isolation")
    endpoint.store = SimpleNamespace(dispatch_admission=lambda _operation: None)
    with pytest.raises(InvocationPreCallRejected, match=NATIVE_ATTACHMENT_UNSUPPORTED):
        endpoint.recover_prepared(prepared.invocation, prepared.request, prepared.receipt, lambda: prepared.envelope,
                                  lambda *_args: pytest.fail("unsupported recovery marked Domain"))

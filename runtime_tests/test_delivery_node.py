"""Real SQLite adapter guards; Domain authorization and Driver are fixtures."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket, InvocationObservation
from runtime.delivery_node import DeliveryBoundaryRejected, LocalNodeEndpoint, logical_payload
from runtime.node import JournalOperation, NodeJournal, OperationIdentityConflict


class DriverFixture:
    evidence_class = "fixture_callback"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def prepare(self, invocation):
        return invocation

    def invoke(self, invocation):
        self.calls += 1
        if self.fail:
            raise OSError("ambiguous fixture call")
        return InvocationObservation(invocation_id=invocation.invocation_id,
                                     dispatch_id=invocation.dispatch_id,
                                     runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
                                     native_dispatch_ref="fixture-dispatch", native_ack_ref="fixture-ack",
                                     response_ref="fixture-response", response={"done": True})


def envelope(journal, activation="message_only"):
    return DeliveryEnvelope(tenant_id="fixture-tenant", message_id="fixture-message", command_id="fixture-command",
        authority_id="fixture-authority", authority_incarnation="fixture-incarnation",
        principal_ref="fixture-principal", grant_ref="fixture-grant",
        operation_id="fixture-operation", endpoint_id="fixture-endpoint", binding_revision=1,
        machine_id=journal.machine_id, node_id=journal.node_id, boot_incarnation=journal.boot_incarnation,
        accepted_state_digest="a" * 64,
        packet=DeliveryPacket(work_item_id="fixture-work", target_scope_id="fixture-scope", target_agent_slot_id="fixture-slot",
            accepted_revision=0, goal="SQLite guard", accepted_state_summary="fixture genesis", request="fixture request",
            source_baseline="fixture-baseline", expected_response="fixture receipt", activation=activation,
            deadline=datetime.now(UTC) + timedelta(minutes=5)))


def fixture_authorize(frame):
    """Explicit test authorization stand-in; these tests prove no Domain Grant."""
    return lambda: frame


def deliver(endpoint, frame, attempt="fixture-attempt"):
    invocation = endpoint.invocation(frame, attempt) if frame.packet.activation == "invoke" else None
    return endpoint.deliver(frame, fixture_authorize(frame), invocation=invocation)


def sqlite_row(path, statement, params=()):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(statement, params).fetchone()


def test_sqlite_early_response_survives_late_inbox(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    frame = envelope(journal)
    journal.append(JournalOperation(frame.operation_id, frame.command_id, frame.message_id, "delivery",
                                    journal.payload_digest(logical_payload(frame))))
    journal.record_receipt(frame.operation_id, "response_received", evidence={"source": "early-response-fixture"})
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot")
    assert deliver(endpoint, frame)["status"] == "delivered"
    assert journal.get_message(frame.message_id).state == "response_received"
    assert journal.recover()["pending_mailbox"] == ()


def test_sqlite_new_boot_keeps_logical_identity_and_one_fixture_invoke(tmp_path):
    path = tmp_path / "node.sqlite"
    original = NodeJournal(path)
    frame, driver = envelope(original, "invoke"), DriverFixture()
    first = LocalNodeEndpoint(original, "fixture-scope", "fixture-slot", driver)
    assert deliver(first, frame)["status"] == "delivered"
    old_receipts = original.receipts(frame.operation_id)
    current = NodeJournal(path)
    assert current.boot_incarnation != original.boot_incarnation
    refreshed = frame.model_copy(update={"boot_incarnation": current.boot_incarnation, "binding_revision": 2})
    endpoint = LocalNodeEndpoint(current, "fixture-scope", "fixture-slot", driver)
    assert deliver(endpoint, refreshed, "replacement-attempt")["status"] == "delivered"
    assert driver.calls == 1 and len(current.list_mailbox()) == 1
    assert current.receipts(frame.operation_id) == old_receipts


def test_sqlite_uncertain_invoke_is_never_automatically_repeated(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    driver, frame = DriverFixture(fail=True), envelope(journal, "invoke")
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    assert deliver(endpoint, frame)["status"] == "uncertain"
    assert deliver(endpoint, frame)["status"] == "uncertain"
    assert driver.calls == 1
    assert [receipt.layer for receipt in journal.receipts(frame.operation_id)] == [
        "accepted_by_authority", "target_inbox_committed", "runtime_dispatched"]


def test_driver_pre_call_rejection_has_no_dispatch_marker(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    driver, frame = DriverFixture(), envelope(journal, "invoke")
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    driver.prepare = lambda invocation: (_ for _ in ()).throw(ValueError("fixture rejection"))
    with pytest.raises(DeliveryBoundaryRejected, match="driver_pre_call_rejected"):
        deliver(endpoint, frame)
    assert driver.calls == 0
    assert [receipt.layer for receipt in journal.receipts(frame.operation_id)] == [
        "accepted_by_authority", "target_inbox_committed"]
    assert sqlite_row(tmp_path / "node.sqlite",
                      "SELECT state FROM delivery_invocations WHERE operation_id=?",
                      (frame.operation_id,)) == ("pre_call_rejected",)


def test_dispatch_marker_is_emitted_before_native_call_and_binds_identity(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    driver, frame = DriverFixture(), envelope(journal, "invoke")
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    marked = []

    def marker(invocation, evidence):
        marked.append((invocation, evidence))

    original = driver.invoke

    def assert_marked(invocation):
        assert marked and marked[0][0] == invocation
        return original(invocation)

    driver.invoke = assert_marked
    invocation = endpoint.invocation(frame, "fixture-attempt")
    result = endpoint.deliver(frame, fixture_authorize(frame), invocation=invocation,
                              mark_dispatched=marker)
    assert result["status"] == "delivered"
    dispatch = next(receipt for receipt in journal.receipts(frame.operation_id)
                    if receipt.layer == "runtime_dispatched")
    assert dispatch.receipt_id == invocation.runtime_dispatched_receipt_id
    assert dispatch.evidence["invocation_id"] == invocation.invocation_id
    assert dispatch.evidence["dispatch_id"] == invocation.dispatch_id
    assert dispatch.evidence["message_id"] == frame.message_id
    assert dispatch.evidence["envelope_digest"] == invocation.envelope_digest
    assert dispatch.evidence["accepted_revision"] == frame.packet.accepted_revision
    assert dispatch.evidence["accepted_state_digest"] == frame.accepted_state_digest


def test_replacement_boot_before_dispatch_fence_prevents_native_call(tmp_path, monkeypatch):
    path = tmp_path / "node.sqlite"
    journal = NodeJournal(path)
    driver, frame = DriverFixture(), envelope(journal, "invoke")
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    invocation = endpoint.invocation(frame, "fixture-attempt")
    original_transaction = journal._transaction
    prepared, resume = Event(), Event()

    @contextmanager
    def pause_after_prepare(*args, **kwargs):
        with original_transaction(*args, **kwargs) as connection:
            yield connection
        state = sqlite_row(path, "SELECT state FROM delivery_invocations WHERE operation_id=?",
                           (frame.operation_id,))
        if state == ("prepared",) and not prepared.is_set():
            prepared.set()
            assert resume.wait(5)

    monkeypatch.setattr(journal, "_transaction", pause_after_prepare)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            endpoint.deliver, frame, fixture_authorize(frame), invocation, lambda *_: None,
        )
        try:
            assert prepared.wait(5)
            replacement = NodeJournal(path, busy_timeout_ms=500)
            assert replacement.boot_incarnation != journal.boot_incarnation
        finally:
            resume.set()
        with pytest.raises(OperationIdentityConflict, match="retired Node boot"):
            future.result(timeout=5)
    assert driver.calls == 0
    assert not sqlite_row(path, "SELECT 1 FROM lifecycle_receipts WHERE operation_id=? "
                                "AND layer='runtime_dispatched'", (frame.operation_id,))


def test_native_call_fence_delays_replacement_until_observation_commit(tmp_path, monkeypatch):
    path = tmp_path / "node.sqlite"
    journal = NodeJournal(path)
    driver, frame = DriverFixture(), envelope(journal, "invoke")
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    invocation = endpoint.invocation(frame, "fixture-attempt")
    entered, release = Event(), Event()
    replacement_begin, replacement_done = Event(), Event()
    original = driver.invoke

    def gated_invoke(request):
        entered.set()
        assert release.wait(5)
        return original(request)

    class ObservedReplacement(NodeJournal):
        def _connect(self):
            connection = super()._connect()
            connection.set_trace_callback(
                lambda statement: replacement_begin.set()
                if statement.strip().upper() == "BEGIN IMMEDIATE" else None,
            )
            return connection

    def replace():
        try:
            return ObservedReplacement(path, busy_timeout_ms=2000)
        finally:
            replacement_done.set()

    monkeypatch.setattr(driver, "invoke", gated_invoke)
    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatch = pool.submit(
            endpoint.deliver, frame, fixture_authorize(frame), invocation, lambda *_: None,
        )
        try:
            assert entered.wait(5)
            replacement_future = pool.submit(replace)
            assert replacement_begin.wait(2)
            assert not replacement_done.wait(0.2)
            assert sqlite_row(path, "SELECT value FROM node_meta WHERE key='boot_incarnation'") == (
                journal.boot_incarnation,
            )
        finally:
            release.set()
        assert dispatch.result(timeout=5)["status"] == "delivered"
        replacement = replacement_future.result(timeout=5)
    assert driver.calls == 1
    assert replacement.boot_incarnation != journal.boot_incarnation
    assert sqlite_row(path, "SELECT state FROM delivery_invocations WHERE operation_id=?",
                      (frame.operation_id,)) == ("acknowledged",)


@pytest.mark.parametrize("field", ["authority_id", "authority_incarnation", "principal_ref", "grant_ref"])
def test_node_rejects_refs_that_differ_from_authorized_committed_envelope(tmp_path, field):
    journal = NodeJournal(tmp_path / "node.sqlite")
    frame, driver = envelope(journal, "invoke"), DriverFixture()
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", "fixture-slot", driver)
    altered = frame.model_copy(update={field: "forged-reference"})
    with pytest.raises(DeliveryBoundaryRejected, match="committed_authorization_reference_mismatch"):
        endpoint.deliver(altered, fixture_authorize(frame),
                         invocation=endpoint.invocation(altered, "fixture-attempt"))
    assert journal.list_mailbox() == () and driver.calls == 0


def test_packet_body_cannot_supply_authorization_refs(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    packet = envelope(journal).packet.model_dump(mode="json") | {"grant_ref": "self-granted"}
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        DeliveryPacket.model_validate_json(json.dumps(packet), strict=True)

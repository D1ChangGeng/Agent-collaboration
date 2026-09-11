"""Actual integrated PG/SQLite/Temporal delivery; callbacks are explicit fixtures."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.delivery import DeliveryDispatcher, DeliveryRejected, DeliveryService, digest
from runtime.delivery_models import (
    DeliveryEnvelope,
    DeliveryPacket,
    EndpointBindingRequest,
    InvocationObservation,
)
from runtime.delivery_node import DeliveryTransportError, LocalNodeEndpoint, logical_payload
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, IdempotencyConflict
from runtime.models import CommandEnvelope
from runtime.node import JournalOperation, NodeJournal


class FixtureDriver:
    evidence_class = "fixture_callback"

    def __init__(self):
        self.calls = []
        self.envelopes = []
        self.fail = False
        self.reject = False

    def prepare(self, invocation):
        if self.reject:
            raise ValueError("explicit fixture pre-call rejection")
        return invocation

    def invoke(self, invocation):
        envelope = invocation.envelope
        self.calls.append(envelope.operation_id)
        self.envelopes.append(invocation)
        if self.fail:
            raise OSError("explicit fixture ambiguous native transport")
        return InvocationObservation(invocation_id=invocation.invocation_id,
                                     dispatch_id=invocation.dispatch_id,
                                     runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
                                     native_dispatch_ref="fixture-dispatch", native_ack_ref="fixture-ack",
                                     response_ref="fixture-response", response={"message_id": envelope.message_id})


def command(authority, kind, target, revision=0, **changes):
    now = datetime.now(UTC)
    values = {"command_id": f"cmd-{uuid.uuid4()}", "idempotency_key": f"key-{uuid.uuid4()}",
              "command_type": kind, "correlation_id": "delivery-test", "tenant_id": authority.context.tenant_id,
              "authority_id": authority.context.authority_id, "authority_incarnation": authority.context.authority_incarnation,
              "principal_ref": authority.context.principal_ref, "grant_ref": authority.context.grant_ref,
              "target_kind": "work_item" if kind == "work_item.create" else "message", "target_id": target,
              "expected_revision": revision, "issued_at": now, "deadline": now + timedelta(minutes=2)}
    values.update(changes)
    return CommandEnvelope(**values)


def query(f, statement, params=()):
    with psycopg.connect(f.dsn) as connection:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def counts(f):
    return tuple(query(f, f"SELECT count(*) FROM {name}")[0][0] for name in (
        "command_dedup", "domain_events", "operations", "outbox", "delivery_messages", "inbox_messages"))


@pytest.fixture
def setup(tmp_path):
    base = os.getenv("ACS_P1_DSN")
    if not base:
        pytest.skip("real PostgreSQL not measured: ACS_P1_DSN is missing")
    schema = "delivery_test_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=10000")
    try:
        authority = DomainAuthority(dsn)
        authority.initialize()
        authority.bootstrap_local_grant(("work_item.create", "delivery.manage", "message.send", "message.read", "runtime.invoke"))
        authority.create_work_item(command(authority, "work_item.create", "work"), "local-scope", "local-slot", "delivery-fixture-baseline")
        driver = FixtureDriver()
        journal = NodeJournal(tmp_path / "node.sqlite")
        endpoint = LocalNodeEndpoint(journal, "local-scope", "local-slot", driver)
        with psycopg.connect(dsn) as connection:
            connection.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) "
                               "VALUES ('reviewer-slot',%s,'local-scope','active')", (authority.tenant_id,))
        reviewer_driver = FixtureDriver()
        reviewer_journal = NodeJournal(tmp_path / "reviewer.sqlite")
        reviewer_endpoint = LocalNodeEndpoint(reviewer_journal, "local-scope", "reviewer-slot", reviewer_driver)
        service = DeliveryService(authority, {"endpoint": endpoint, "reviewer-endpoint": reviewer_endpoint})
        service.bind_endpoint(command(authority, "message.bind", "endpoint"), EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="local-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
        service.bind_endpoint(command(authority, "message.bind", "reviewer-endpoint"), EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="reviewer-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
        yield SimpleNamespace(authority=authority, driver=driver, journal=journal, endpoint=endpoint,
                              reviewer_driver=reviewer_driver, reviewer_journal=reviewer_journal,
                              service=service, dispatcher=DeliveryDispatcher(service), dsn=dsn, path=tmp_path / "node.sqlite")
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def send(f, *, activation="message_only", ttl=60, maximum_attempts=3,
         target_scope="local-scope", target_slot="local-slot", endpoint_id="endpoint"):
    cmd = command(f.authority, "message.send", f"message-{uuid.uuid4()}")
    packet = DeliveryPacket(work_item_id="work", target_scope_id=target_scope, target_agent_slot_id=target_slot,
        accepted_revision=0, goal="Exercise durable delivery", accepted_state_summary="explicit genesis revision 0",
        request="Read this packet; no reasoning unless invoke was separately authorized", constraints=("fixture scope",),
        source_baseline="delivery-fixture-baseline", expected_response="layered receipt", required_evidence=("actual Inbox commit",),
        activation=activation, deadline=datetime.now(UTC) + timedelta(seconds=ttl), maximum_attempts=maximum_attempts)
    result = f.service.send_message(cmd, packet, endpoint_id=endpoint_id, binding_revision=1)
    identity = {"tenant_id": f.authority.tenant_id, "message_id": cmd.target_id, "operation_id": result.operation_id}
    return identity, cmd, packet, result


def due(f, message_id):
    query(f, "UPDATE delivery_messages SET next_attempt_at=clock_timestamp() WHERE message_id=%s", (message_id,))


def message(f, message_id):
    return query(f, "SELECT state,last_error,attempts FROM delivery_messages WHERE message_id=%s", (message_id,))[0]


@pytest.mark.parametrize("action", ["message.bind", "message.send"])
def test_grant_expiry_while_waiting_for_endpoint_lock_rolls_back(setup, action):
    f = setup
    expiry = datetime.now(UTC) + timedelta(seconds=2)
    query(f, "UPDATE grants SET expires_at=%s WHERE grant_ref=%s",
          (expiry, f.authority.context.grant_ref))
    before = counts(f)
    with psycopg.connect(f.dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute("SELECT endpoint_id FROM delivery_endpoints WHERE endpoint_id='endpoint' FOR UPDATE")
        blocker_pid = blocker.info.backend_pid

        def run():
            if action == "message.send":
                return send(f)
            return f.service.bind_endpoint(
                command(f.authority, "message.bind", "endpoint", revision=1),
                EndpointBindingRequest(scope_id="local-scope", agent_slot_id="local-slot",
                                       expires_at=datetime.now(UTC) + timedelta(minutes=1)),
            )

        future = pool.submit(run)
        stop = time.monotonic() + 1.5
        while time.monotonic() < stop:
            waiting = query(
                f, "SELECT count(*) FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))",
                (blocker_pid,),
            )[0][0]
            if waiting:
                break
            time.sleep(0.02)
        assert waiting, "test did not reach the endpoint row lock"
        time.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.1)
        blocker.commit()
        with pytest.raises(AuthorizationDenied):
            future.result(timeout=5)
    assert counts(f) == before


def test_commit_then_actual_node_inbox_projection_and_exact_send_replay(setup):
    f = setup
    identity, cmd, packet, first = send(f)
    before = counts(f)
    duplicate = f.service.send_message(cmd, packet, endpoint_id="endpoint", binding_revision=1)
    assert duplicate.duplicate and duplicate.operation_id == first.operation_id and counts(f) == before
    assert f.journal.list_mailbox() == ()
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"
    assert f.journal.get_message(cmd.target_id).state == "target_inbox_committed"
    assert query(f, "SELECT count(*) FROM inbox_messages") == [(1,)]
    assert query(f, "SELECT layer FROM delivery_receipts ORDER BY observed_at") == [("accepted_by_authority",), ("target_inbox_committed",)]
    assert f.driver.calls == []
    before = counts(f)
    assert DeliveryDispatcher(DeliveryService(f.authority, {"endpoint": f.endpoint})).dispatch(identity)["status"] == "delivered"
    assert counts(f) == before
    with pytest.raises(IdempotencyConflict):
        f.service.send_message(cmd, packet.model_copy(update={"request": "changed request"}), endpoint_id="endpoint", binding_revision=1)
    assert counts(f) == before


def test_send_permission_is_not_invoke_permission(setup):
    f = setup
    query(f, "UPDATE grants SET permissions=permissions-'runtime.invoke' WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        send(f, activation="invoke")
    assert counts(f) == before and f.driver.calls == []
    identity, _, _, _ = send(f)
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"


@pytest.mark.parametrize("activation", ["message_only", "invoke"])
@pytest.mark.parametrize("owner_status", ["active", "revoked"])
def test_same_scope_delivery_targets_reviewer_independently_of_work_item_owner(setup, activation, owner_status):
    f = setup
    query(f, "UPDATE agent_slots SET status=%s WHERE agent_slot_id='local-slot'", (owner_status,))
    assert query(f, "SELECT agent_slot_id FROM work_items WHERE work_item_id='work'") == [("local-slot",)]
    identity, cmd, _, _ = send(f, activation=activation, target_slot="reviewer-slot", endpoint_id="reviewer-endpoint")
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"
    assert f.journal.list_mailbox() == () and f.driver.calls == []
    received = f.reviewer_journal.get_message(identity["message_id"])
    assert received is not None
    logical = json.loads(received.payload_json)["value"]
    assert logical["packet"]["target_agent_slot_id"] == "reviewer-slot"
    assert logical["packet"]["work_item_id"] == "work"
    for field in ("authority_id", "authority_incarnation", "principal_ref", "grant_ref"):
        assert logical[field] == getattr(cmd, field)
    assert len(f.reviewer_driver.calls) == (1 if activation == "invoke" else 0)
    if activation == "invoke":
        observed = f.reviewer_driver.envelopes[0]
        assert (observed.envelope.grant_ref == cmd.grant_ref
                and observed.envelope.packet.deadline <= cmd.deadline)
    assert query(f, "SELECT target_agent_slot_id FROM inbox_messages WHERE message_id=%s",
                 (identity["message_id"],)) == [("reviewer-slot",)]


@pytest.mark.parametrize("phase", ["send", "queued"])
def test_receiving_slot_must_be_active_at_send_and_dispatch(setup, phase):
    f = setup
    if phase == "queued":
        identity, _, _, _ = send(f, activation="invoke", target_slot="reviewer-slot", endpoint_id="reviewer-endpoint")
    query(f, "UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='reviewer-slot'")
    before = counts(f)
    if phase == "send":
        with pytest.raises(DeliveryRejected, match="target_slot_unavailable"):
            send(f, activation="invoke", target_slot="reviewer-slot", endpoint_id="reviewer-endpoint")
        assert counts(f) == before
    else:
        assert f.dispatcher.dispatch(identity)["status"] == "blocked"
        assert message(f, identity["message_id"])[1] == "target_slot_unavailable"
    assert f.reviewer_journal.list_mailbox() == () and f.reviewer_driver.calls == []


def test_endpoint_cannot_substitute_another_slot_in_the_same_scope(setup):
    f = setup
    before = counts(f)
    with pytest.raises(DeliveryRejected, match="endpoint_binding_changed"):
        send(f, target_slot="reviewer-slot", endpoint_id="endpoint")
    assert counts(f) == before


@pytest.mark.parametrize("activation", ["message_only", "invoke"])
def test_cross_scope_context_is_denied_even_with_target_scope_permissions(setup, tmp_path, activation):
    f = setup
    # Explicit test administration gives the sender real target-Scope Grants;
    # the existing WorkItem's Scope and owner remain unchanged.
    query(f, "INSERT INTO scopes(scope_id,tenant_id,status) VALUES ('other-scope',%s,'active')", (f.authority.tenant_id,))
    query(f, "INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES ('other-slot',%s,'other-scope','active')",
          (f.authority.tenant_id,))
    query(f, "UPDATE grants SET scope_id='other-scope' WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    journal = NodeJournal(tmp_path / "other-scope.sqlite")
    endpoint = LocalNodeEndpoint(journal, "other-scope", "other-slot", f.driver)
    service = DeliveryService(f.authority, {"other-endpoint": endpoint})
    service.bind_endpoint(command(f.authority, "message.bind", "other-endpoint"), EndpointBindingRequest(
        scope_id="other-scope", agent_slot_id="other-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    before = counts(f)
    with pytest.raises(DeliveryRejected, match="work_item_precondition_changed"):
        send(SimpleNamespace(authority=f.authority, service=service), activation=activation,
             target_scope="other-scope", target_slot="other-slot", endpoint_id="other-endpoint")
    assert counts(f) == before and journal.list_mailbox() == () and f.driver.calls == []


@pytest.mark.parametrize("field", ["authority_id", "authority_incarnation", "principal_ref", "grant_ref"])
def test_durable_envelope_auth_refs_cannot_differ_from_committed_command(setup, field):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    envelope = query(f, "SELECT envelope_json FROM delivery_messages WHERE message_id=%s", (identity["message_id"],))[0][0]
    envelope[field] = "corrupted-reference"
    # Rehashing a corrupted envelope cannot override the separately sealed Command.
    query(f, "UPDATE delivery_messages SET envelope_json=%s,envelope_hash=%s WHERE message_id=%s",
          (json.dumps(envelope), digest(envelope), identity["message_id"]))
    assert f.dispatcher.dispatch(identity)["status"] == "blocked"
    assert message(f, identity["message_id"])[1] == "durable_authorization_reference_mismatch"
    assert f.journal.list_mailbox() == () and f.driver.calls == []


@pytest.mark.parametrize("change,error,state", [
    ("revoke", "current_grant_denied", "blocked"),
    ("invoke_permission", "current_grant_denied", "blocked"),
    ("accepted", "accepted_revision_changed", "blocked"),
    ("revision", "work_item_precondition_changed", "blocked"),
    ("policy", "scope_policy_changed", "blocked"),
    ("deadline", "deadline_expired", "expired"),
])
def test_queued_command_rechecks_actual_authority_and_source_state(setup, change, error, state):
    f = setup
    identity, _, _, _ = send(f, activation="invoke", ttl=1 if change == "deadline" else 60)
    if change == "revoke":
        query(f, "UPDATE grants SET revoked_at=clock_timestamp()")
    elif change == "invoke_permission":
        query(f, "UPDATE grants SET permissions=permissions-'runtime.invoke'")
    elif change == "accepted":
        # Explicit authority-state change fixture, not a claim of accepted evidence.
        query(f, "INSERT INTO accepted_state_revisions(tenant_id,work_item_id,revision,baseline_ref,evidence_refs,review_ref,effect_refs,readback_refs) "
                 "VALUES (%s,'work',1,'delivery-fixture-baseline','[]','fixture-review','[]','[]')", (f.authority.tenant_id,))
    elif change == "revision":
        query(f, "UPDATE work_items SET revision=1")
    elif change == "policy":
        query(f, "UPDATE scopes SET policy='{\"changed\":true}'")
    else:
        time.sleep(1.1)
    assert f.dispatcher.dispatch(identity)["status"] == state
    assert message(f, identity["message_id"])[:2] == (state, error)
    assert f.journal.list_mailbox() == () and f.driver.calls == []
    assert query(f, "SELECT count(*) FROM inbox_messages") == [(0,)]


def test_ack_loss_retries_same_identity_without_second_fixture_invoke(setup):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    original = f.endpoint.deliver
    first = True
    def lose_ack(*args, **kwargs):
        nonlocal first
        response = original(*args, **kwargs)
        if first:
            first = False
            raise DeliveryTransportError("injected ACK loss after real Node commit")
        return response
    f.endpoint.deliver = lose_ack
    assert f.dispatcher.dispatch(identity)["status"] == "retry_wait"
    assert query(f, "SELECT count(*) FROM inbox_messages") == [(0,)]
    assert f.journal.get_message(identity["message_id"]).state == "response_received"
    due(f, identity["message_id"])
    assert DeliveryDispatcher(f.service).dispatch(identity)["status"] == "delivered"
    assert f.driver.calls == [identity["operation_id"]]
    assert query(f, "SELECT ordinal,status FROM delivery_attempts ORDER BY ordinal") == [(1, "retry_wait"), (2, "delivered")]
    assert query(f, "SELECT count(*) FROM inbox_messages") == [(1,)]


def test_ambiguous_native_callback_is_not_reinvoked(setup):
    f = setup
    f.driver.fail = True
    identity, _, _, _ = send(f, activation="invoke")
    assert f.dispatcher.dispatch(identity)["status"] == "uncertain"
    assert DeliveryDispatcher(f.service).dispatch(identity)["status"] == "uncertain"
    assert f.driver.calls == [identity["operation_id"]]
    assert query(f, "SELECT layer FROM delivery_receipts ORDER BY observed_at") == [
        ("accepted_by_authority",), ("runtime_dispatched",), ("target_inbox_committed",)]


def test_pre_call_rejection_is_blocked_without_activation_or_dispatch_receipt(setup):
    f = setup
    f.driver.reject = True
    identity, _, _, _ = send(f, activation="invoke")
    assert f.dispatcher.dispatch(identity)["status"] == "blocked"
    assert f.driver.calls == []
    assert query(
        f,
        "SELECT activation_node_id,activation_dispatch_id,receipt_high_water FROM delivery_messages",
    ) == [(None, None, "target_inbox_committed")]
    assert query(f, "SELECT layer FROM delivery_receipts ORDER BY observed_at") == [
        ("accepted_by_authority",), ("target_inbox_committed",)]


def test_postgres_dispatch_marker_and_location_commit_before_native_call(setup):
    f = setup
    identity, _, packet, _ = send(f, activation="invoke")
    original = f.driver.invoke

    def inspect_marker(invocation):
        rows = query(
            f,
            "SELECT m.activation_node_id,m.activation_dispatch_id,m.activation_receipt_id,"
            "m.receipt_high_water,a.status,r.receipt_id,r.dispatch_id,r.evidence_json "
            "FROM delivery_messages m JOIN delivery_attempts a USING(tenant_id,message_id) "
            "JOIN delivery_receipts r USING(tenant_id,message_id) "
            "WHERE m.message_id=%s AND r.layer='runtime_dispatched'",
            (identity["message_id"],),
        )
        assert rows == [(
            invocation.envelope.node_id, invocation.dispatch_id,
            invocation.runtime_dispatched_receipt_id, "runtime_dispatched",
            "runtime_dispatched", invocation.runtime_dispatched_receipt_id,
            invocation.dispatch_id, rows[0][7],
        )]
        evidence = rows[0][7]
        assert evidence["invocation_id"] == invocation.invocation_id
        assert evidence["message_id"] == identity["message_id"]
        assert evidence["accepted_revision"] == packet.accepted_revision
        assert evidence["accepted_state_digest"] == invocation.accepted_state_digest
        return original(invocation)

    f.driver.invoke = inspect_marker
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"


def test_postgres_receipt_high_water_does_not_regress_on_late_lower_layer(setup):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"
    assert query(f, "SELECT receipt_high_water FROM delivery_messages") == [("response_received",)]
    query(f, "DELETE FROM delivery_receipts WHERE message_id=%s AND layer='target_inbox_committed'",
          (identity["message_id"],))
    with f.authority._connect() as connection, connection.cursor() as cursor:
        row = f.dispatcher._load(cursor, identity)
        f.dispatcher._record_receipt(
            cursor, row, "late-inbox-receipt", "target_inbox_committed",
            {"message_id": identity["message_id"], "source": "late-projection-fixture"},
        )
    assert query(f, "SELECT receipt_high_water FROM delivery_messages") == [("response_received",)]


def test_attempt_selection_is_immutable_when_binding_changes_after_prepare(setup, tmp_path):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    original_selection = {}

    def rebind_after_prepare(_identity):
        original_selection.update(query(
            f, "SELECT selection_json FROM delivery_attempts WHERE message_id=%s",
            (identity["message_id"],),
        )[0][0])
        journal = NodeJournal(tmp_path / "replacement.sqlite")
        replacement = LocalNodeEndpoint(journal, "local-scope", "local-slot", f.driver)
        f.service.endpoints["endpoint"] = replacement
        f.service.bind_endpoint(
            command(f.authority, "message.bind", "endpoint", 1),
            EndpointBindingRequest(scope_id="local-scope", agent_slot_id="local-slot",
                                   expires_at=datetime.now(UTC) + timedelta(minutes=5)),
        )

    f.dispatcher.after_claim = rebind_after_prepare
    assert f.dispatcher.dispatch(identity)["status"] == "blocked"
    selected = query(f, "SELECT selection_json FROM delivery_attempts WHERE message_id=%s",
                     (identity["message_id"],))[0][0]
    assert selected == original_selection
    assert selected["revision"] == 1
    assert query(f, "SELECT activation_node_id FROM delivery_messages") == [(None,)]
    assert f.driver.calls == []


@pytest.mark.parametrize("ledger", ["operation", "outbox", "dedup", "event"])
def test_recovery_cross_checks_independent_domain_ledger_records(setup, ledger):
    f = setup
    identity, _, _, _ = send(f)
    mutations = {
        "operation": "UPDATE operations SET status='failed' WHERE operation_id=%s",
        "outbox": "UPDATE outbox SET topic='corrupt' WHERE operation_id=%s",
        "dedup": "UPDATE command_dedup SET canonical_hash=%s WHERE command_id=(SELECT command_id FROM delivery_messages WHERE operation_id=%s)",
        "event": "UPDATE domain_events SET to_state='corrupt' WHERE command_id=(SELECT command_id FROM delivery_messages WHERE operation_id=%s)",
    }
    params = (("0" * 64, identity["operation_id"]) if ledger == "dedup"
              else (identity["operation_id"],))
    query(f, mutations[ledger], params)
    assert f.dispatcher.dispatch(identity)["status"] == "blocked"
    assert message(f, identity["message_id"])[1] == "domain_ledger_conflict"
    assert f.journal.list_mailbox() == () and f.driver.calls == []


@pytest.mark.parametrize("activation", ["message_only", "invoke"])
def test_real_node_boot_restart_and_authorized_rebind_preserve_logical_inbox(setup, activation):
    f = setup
    identity, _, _, _ = send(f, activation=activation)
    original = f.endpoint.deliver
    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise DeliveryTransportError("injected ACK loss before Core projection")
    f.endpoint.deliver = lose_ack
    assert f.dispatcher.dispatch(identity)["status"] == "retry_wait"
    old_receipts = f.journal.receipts(identity["operation_id"])
    reopened = NodeJournal(f.path)  # Actual new boot, no reused explicit incarnation.
    assert reopened.boot_incarnation != f.journal.boot_incarnation
    replacement = LocalNodeEndpoint(reopened, "local-scope", "local-slot", f.driver)
    service = DeliveryService(f.authority, {"endpoint": replacement})
    service.bind_endpoint(command(f.authority, "message.bind", "endpoint", 1), EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="local-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    due(f, identity["message_id"])
    assert DeliveryDispatcher(service).dispatch(identity)["status"] == "delivered"
    assert reopened.receipts(identity["operation_id"]) == old_receipts
    assert len(reopened.list_mailbox()) == 1
    assert len(f.driver.calls) == (1 if activation == "invoke" else 0)
    selection = query(f, "SELECT selection_revision,selection_json->>'boot_incarnation' FROM delivery_attempts WHERE ordinal=2")
    assert selection == [(2, reopened.boot_incarnation)]


def test_early_response_cannot_regress_during_actual_inbox_commit(setup):
    f = setup
    identity, _, _, _ = send(f)
    value = query(f, "SELECT envelope_json FROM delivery_messages")[0][0]
    envelope = DeliveryEnvelope.model_validate_json(json.dumps(value))
    op = JournalOperation(envelope.operation_id, envelope.command_id, envelope.message_id, "delivery",
                          f.journal.payload_digest(logical_payload(envelope)))
    f.journal.append(op)
    f.journal.record_receipt(op.operation_id, "response_received", evidence={"source": "explicit early-response fixture"})
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"
    assert f.journal.get_message(op.message_id).state == "response_received"
    assert f.journal.recover()["pending_mailbox"] == ()


def test_missing_endpoint_exhausts_bounded_budget_without_node_actions(setup):
    f = setup
    identity, _, _, _ = send(f, maximum_attempts=2)
    dispatcher = DeliveryDispatcher(DeliveryService(f.authority, {}))
    assert dispatcher.dispatch(identity)["status"] == "retry_wait"
    due(f, identity["message_id"])
    assert dispatcher.dispatch(identity)["status"] == "budget_exhausted"
    due(f, identity["message_id"])
    assert dispatcher.dispatch(identity)["status"] == "budget_exhausted"
    assert message(f, identity["message_id"])[2] == 2 and f.journal.list_mailbox() == ()


def test_replacement_node_cannot_repeat_an_unreconciled_native_activation(setup, tmp_path):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    deliver = f.endpoint.deliver
    def lost(*args, **kwargs):
        deliver(*args, **kwargs)
        raise DeliveryTransportError("lost ACK from original activation location")
    f.endpoint.deliver = lost
    assert f.dispatcher.dispatch(identity)["status"] == "retry_wait"
    replacement_journal = NodeJournal(tmp_path / "different-node.sqlite")
    replacement = LocalNodeEndpoint(replacement_journal, "local-scope", "local-slot", f.driver)
    service = DeliveryService(f.authority, {"endpoint": replacement})
    service.bind_endpoint(command(f.authority, "message.bind", "endpoint", 1), EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="local-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    due(f, identity["message_id"])
    assert DeliveryDispatcher(service).dispatch(identity)["status"] == "uncertain"
    assert f.driver.calls == [identity["operation_id"]] and replacement_journal.list_mailbox() == ()


def test_missing_endpoint_does_not_pin_activation_before_new_node_rebind(setup, tmp_path):
    f = setup
    identity, _, _, _ = send(f, activation="invoke")
    missing = DeliveryDispatcher(DeliveryService(f.authority, {}))
    assert missing.dispatch(identity)["status"] == "retry_wait"
    assert query(f, "SELECT activation_node_id,activation_machine_id FROM delivery_messages") == [(None, None)]
    replacement_journal = NodeJournal(tmp_path / "available-node.sqlite")
    replacement = LocalNodeEndpoint(replacement_journal, "local-scope", "local-slot", f.driver)
    service = DeliveryService(f.authority, {"endpoint": replacement})
    service.bind_endpoint(command(f.authority, "message.bind", "endpoint", 1), EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="local-slot", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    due(f, identity["message_id"])
    assert DeliveryDispatcher(service).dispatch(identity)["status"] == "delivered"
    assert f.driver.calls == [identity["operation_id"]]
    assert f.journal.list_mailbox() == () and len(replacement_journal.list_mailbox()) == 1


def test_outbox_is_not_dispatched_until_sender_transaction_commits(setup):
    f = setup
    sender = DomainAuthority(f.dsn, context=f.authority.context)
    sender_service = DeliveryService(sender, {"endpoint": f.endpoint})
    original_connect = sender._connect
    prepared, release = Event(), Event()
    @contextmanager
    def paused_transaction():
        with original_connect() as connection:
            yield connection
            prepared.set()
            assert release.wait(10)
    sender._connect = paused_transaction
    with ThreadPoolExecutor(max_workers=1) as pool:
        operation = pool.submit(send, SimpleNamespace(service=sender_service, authority=sender))
        try:
            assert prepared.wait(10)
            assert f.dispatcher.pending() == []
            assert query(f, "SELECT count(*) FROM delivery_messages") == [(0,)]
            assert f.journal.list_mailbox() == ()
        finally:
            release.set()
        identity, _, _, _ = operation.result(timeout=10)
    assert f.dispatcher.pending() == [identity]
    assert f.dispatcher.dispatch(identity)["status"] == "delivered"


@pytest.mark.parametrize("activation", ["message_only", "invoke"])
def test_real_core_process_crash_after_committed_attempt_recovers(setup, activation):
    f = setup
    identity, _, _, _ = send(f, activation=activation)
    child = """
import json,os,sys,runtime
from types import SimpleNamespace
runtime.__path__.insert(0,sys.argv[1])
from runtime.domain import DomainAuthority
from runtime.delivery import DeliveryService,DeliveryDispatcher
# Descriptor-only test proxy: this process dies before contacting the Node.
# The actual parent Node remains alive; no Node restart/transport is claimed here.
descriptor=json.loads(sys.argv[3])
endpoint=SimpleNamespace(descriptor=lambda:descriptor)
d=DeliveryDispatcher(DeliveryService(DomainAuthority(os.environ['DELIVERY_TEST_DSN']),{'endpoint':endpoint}))
d.after_claim=lambda identity:os._exit(83)
d.dispatch(json.loads(sys.argv[2]))
"""
    env = dict(os.environ, DELIVERY_TEST_DSN=f.dsn)
    result = subprocess.run([sys.executable, "-c", child, str(Path(__file__).resolve().parents[1] / "runtime"),
                             json.dumps(identity), json.dumps(f.endpoint.descriptor())],
                            env=env, capture_output=True, timeout=15, check=False)
    assert result.returncode == 83, result.stderr.decode()
    assert query(f, "SELECT status,finished_at FROM delivery_attempts") == [("prepared", None)]
    assert f.journal.list_mailbox() == ()
    assert f.driver.calls == []  # A reservation is not evidence of a native call.
    assert DeliveryDispatcher(f.service, worker_id="replacement-core").dispatch(identity)["status"] == "delivered"
    assert query(f, "SELECT ordinal,status FROM delivery_attempts ORDER BY ordinal") == [(1, "delivered")]
    assert len(f.journal.list_mailbox()) == 1
    assert len(f.driver.calls) == (1 if activation == "invoke" else 0)


def test_real_temporal_activity_delivers_sqlite_inbox_and_reuses_workflow(setup):
    endpoint, namespace = os.getenv("ACS_P1_TEMPORAL_ENDPOINT"), os.getenv("ACS_P1_TEMPORAL_NAMESPACE")
    if not endpoint or not namespace:
        pytest.skip("real Temporal endpoint/namespace not configured")
    from temporalio.client import Client

    from runtime.delivery_temporal import delivery_worker, submit_delivery
    f = setup
    identity, _, _, _ = send(f)
    original = f.endpoint.deliver
    lost = False
    def lose_once(*args, **kwargs):
        nonlocal lost
        observed = original(*args, **kwargs)
        if not lost:
            lost = True
            raise DeliveryTransportError("Temporal activity ACK-loss injection")
        return observed
    f.endpoint.deliver = lose_once
    async def run():
        client = await Client.connect(endpoint, namespace=namespace)
        queue = "delivery-test-" + uuid.uuid4().hex
        async with delivery_worker(client, queue, f.dispatcher):
            handle = await submit_delivery(client, queue, f.dispatcher, identity)
            result = await handle.result()
            duplicate = await submit_delivery(client, queue, f.dispatcher, identity)
            assert (await duplicate.describe()).run_id == (await handle.describe()).run_id
            return result
    assert asyncio.run(run())["status"] == "delivered"
    assert len(f.journal.list_mailbox()) == 1 and f.driver.calls == []
    assert query(f, "SELECT ordinal,status FROM delivery_attempts ORDER BY ordinal") == [(1, "retry_wait"), (2, "delivered")]


def test_existing_temporal_run_repairs_missing_postgres_run_reference(setup, monkeypatch):
    from runtime import delivery_temporal

    f = setup
    identity, _, _, _ = send(f)
    workflow_id = f"acs-delivery/{identity['operation_id']}"
    payload_hash = delivery_temporal.hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()

    class AlreadyStarted(Exception):
        pass

    class Description:
        run_id = "existing-run-id"

        async def memo(self):
            return {"acs_delivery_identity_hash": payload_hash}

    class Handle:
        id = workflow_id

        async def describe(self):
            return Description()

    class Client:
        async def start_workflow(self, *args, **kwargs):
            raise AlreadyStarted()

        def get_workflow_handle(self, requested_id, run_id=None):
            assert requested_id == workflow_id
            if run_id is not None:
                assert run_id == "existing-run-id"
            return Handle()

    monkeypatch.setattr(delivery_temporal, "WorkflowAlreadyStartedError", AlreadyStarted)
    handle = asyncio.run(delivery_temporal.submit_delivery(
        Client(), "fixture-queue", f.dispatcher, identity,
    ))
    assert handle.id == workflow_id
    assert query(
        f, "SELECT provider_workflow_id,provider_run_id FROM operations WHERE operation_id=%s",
        (identity["operation_id"],),
    ) == [(workflow_id, "existing-run-id")]


@pytest.mark.parametrize("maximum_attempts", [1, 3])
def test_prepared_node_invocation_reuses_the_same_attempt_after_core_loss(
    setup,
    monkeypatch,
    maximum_attempts,
):
    f = setup
    identity, _, _, result = send(
        f,
        activation="invoke",
        maximum_attempts=maximum_attempts,
    )
    original_prepare = f.driver.prepare

    class CoreInterrupted(BaseException):
        pass

    def interrupt_before_dispatch(invocation):
        with closing(sqlite3.connect(f.path)) as connection:
            assert connection.execute(
                "SELECT state FROM delivery_invocations WHERE operation_id=?",
                (result.operation_id,),
            ).fetchone() == ("prepared",)
        raise CoreInterrupted()

    monkeypatch.setattr(f.driver, "prepare", interrupt_before_dispatch)
    with pytest.raises(CoreInterrupted):
        f.dispatcher.dispatch(identity)
    assert f.driver.calls == []
    assert query(
        f,
        "SELECT count(*) FROM delivery_receipts WHERE layer='runtime_dispatched'",
    ) == [(0,)]

    monkeypatch.setattr(f.driver, "prepare", original_prepare)
    recovered = DeliveryDispatcher(
        f.service,
        worker_id="replacement-core",
    ).dispatch(identity)

    assert recovered["status"] == "delivered"
    assert f.driver.calls == [result.operation_id]
    assert query(
        f,
        "SELECT ordinal,status FROM delivery_attempts ORDER BY ordinal",
    ) == [(1, "delivered")]


@pytest.mark.parametrize("maximum_attempts", [1, 3])
def test_dispatched_attempt_stays_uncertain_across_core_loss_at_budget_boundary(
    setup,
    monkeypatch,
    maximum_attempts,
):
    f = setup
    identity, _, _, result = send(
        f,
        activation="invoke",
        maximum_attempts=maximum_attempts,
    )
    original_invoke = f.driver.invoke

    class CoreInterrupted(BaseException):
        pass

    def interrupt_after_call(invocation):
        original_invoke(invocation)
        raise CoreInterrupted()

    monkeypatch.setattr(f.driver, "invoke", interrupt_after_call)
    with pytest.raises(CoreInterrupted):
        f.dispatcher.dispatch(identity)
    assert f.driver.calls == [result.operation_id]
    assert query(
        f,
        "SELECT count(*) FROM delivery_receipts WHERE layer='runtime_dispatched'",
    ) == [(1,)]

    monkeypatch.setattr(f.driver, "invoke", original_invoke)
    recovered = DeliveryDispatcher(
        f.service,
        worker_id="replacement-core",
    ).dispatch(identity)

    assert recovered["status"] == "uncertain"
    assert f.driver.calls == [result.operation_id]


def test_prepared_attempt_survives_temporary_endpoint_unavailability(
    setup,
    monkeypatch,
):
    f = setup
    identity, _, _, result = send(f, activation="invoke", maximum_attempts=3)
    original_prepare = f.driver.prepare

    class CoreInterrupted(BaseException):
        pass

    def interrupt_before_dispatch(_invocation):
        raise CoreInterrupted()

    monkeypatch.setattr(f.driver, "prepare", interrupt_before_dispatch)
    with pytest.raises(CoreInterrupted):
        f.dispatcher.dispatch(identity)
    monkeypatch.setattr(f.driver, "prepare", original_prepare)

    endpoint = f.service.endpoints.pop("endpoint")
    replacement = DeliveryDispatcher(f.service, worker_id="replacement-core")
    assert replacement.dispatch(identity)["status"] == "retry_wait"
    assert query(
        f,
        "SELECT ordinal,status,finished_at IS NULL FROM delivery_attempts",
    ) == [(1, "prepared", True)]

    f.service.endpoints["endpoint"] = endpoint
    due(f, identity["message_id"])
    recovered = replacement.dispatch(identity)

    assert recovered["status"] == "delivered"
    assert f.driver.calls == [result.operation_id]
    assert query(
        f,
        "SELECT ordinal,status FROM delivery_attempts ORDER BY ordinal",
    ) == [(1, "delivered")]

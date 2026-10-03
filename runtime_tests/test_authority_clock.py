"""Canonical database time remains independent of application host clocks."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from nacl.signing import SigningKey

import runtime.domain as domain_module
import runtime.lease_authority as lease_module
import runtime.receiver_domain as receiver_module
import runtime.recovery as recovery_module
from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    ReceiverTransportAuthority,
)
from runtime.recovery import (
    BridgeAuthoritySnapshot,
    IncidentOpenCommand,
    NodeResponseOutbox,
    PostgresHumanBridgeAuthority,
)
from runtime.recovery_models import BoundaryRejected, RecoveryPath, canonical_digest
from runtime_tests.test_domain_ledger import isolated_dsn  # noqa: F401 - imported pytest fixture
from runtime_tests.test_recovery import identity as response_identity
from runtime_tests.test_recovery import observation as response_observation
from runtime_tests.test_recovery_postgres import postgres_dsn as recovery_postgres_dsn  # noqa: F401
from runtime_tests.test_recovery_postgres import seed_message

INSTANT = datetime(2026, 10, 3, 3, tzinfo=UTC)


class HostClockMustNotBeUsed(datetime):
    @classmethod
    def now(cls, tz=None):
        raise AssertionError("authority decisions must use the database clock")


class ClockCursor:
    def __init__(self, authority, *, now=INSTANT, grant_expiry=None, after_grant_lock=None):
        self.authority = authority
        self.now = now
        self.grant_expiry = grant_expiry or now + timedelta(hours=1)
        self.after_grant_lock = after_grant_lock
        self.statements = []
        self.statement = ""
        self.on_retire = None

    def execute(self, statement, parameters=()):
        self.statement = statement
        self.statements.append((statement, parameters))
        if statement.startswith("SELECT g.scope_id") and self.after_grant_lock is not None:
            self.now = self.after_grant_lock
        if statement.startswith("UPDATE authority_transport_keys") and self.on_retire is not None:
            self.now = self.on_retire

    def fetchone(self):
        if self.statement == "SELECT clock_timestamp()":
            return (self.now,)
        if self.statement.startswith("SELECT g.scope_id"):
            return ("local-scope", ["work_item.create"], self.grant_expiry)
        if self.statement.startswith("SELECT revision FROM"):
            return None
        raise AssertionError("unexpected clock fixture query: " + self.statement)

    def fetchall(self):
        if self.statement.startswith("WITH RECURSIVE ancestry"):
            context = self.authority.context
            return [(context.grant_ref, 0, False, context.tenant_id, ["work_item.create"],
                     self.grant_expiry, None, context.authority_id, context.authority_incarnation,
                     "active", {}, None)]
        raise AssertionError("unexpected clock fixture query: " + self.statement)


@pytest.fixture
def authority():
    return DomainAuthority("dbname=clock-unit options='-csearch_path=clock_schema -clock_timeout=5000'")


def command(authority, **overrides):
    context = authority.context
    values = {"command_id": "clock-command", "command_type": "work_item.create",
        "idempotency_key": "clock-key", "correlation_id": "clock-test", "tenant_id": context.tenant_id,
        "authority_id": context.authority_id, "authority_incarnation": context.authority_incarnation,
        "principal_ref": context.principal_ref, "grant_ref": context.grant_ref, "target_kind": "work_item",
        "target_id": "work-clock", "expected_revision": 0, "issued_at": INSTANT - timedelta(seconds=1),
        "deadline": INSTANT + timedelta(minutes=5)}
    values.update(overrides)
    return CommandEnvelope(**values)


def forbid_host_clock(monkeypatch):
    for module in (domain_module, lease_module, receiver_module):
        monkeypatch.setattr(module, "datetime", HostClockMustNotBeUsed)


def test_canonical_now_normalizes_database_offset_and_refreshes_the_same_cursor(authority):
    cursor = ClockCursor(authority, now=INSTANT.astimezone(timezone(timedelta(hours=9))))
    first = authority.canonical_now(cursor)
    cursor.now += timedelta(seconds=3)
    second = authority.canonical_now(cursor)
    assert first == INSTANT and first.tzinfo is UTC
    assert second == INSTANT + timedelta(seconds=3) and second.tzinfo is UTC
    assert cursor.statements == [("SELECT clock_timestamp()", ()), ("SELECT clock_timestamp()", ())]


def test_canonical_now_rejects_naive_database_time(authority):
    with pytest.raises(ValueError, match="timezone-aware"):
        authority.canonical_now(ClockCursor(authority, now=INSTANT.replace(tzinfo=None)))


def test_connection_sets_utc_before_any_transaction_and_preserves_dsn_options(authority, monkeypatch):
    connection = Mock()
    connect = Mock(return_value=connection)
    monkeypatch.setattr(domain_module.psycopg, "connect", connect)
    assert authority._connect() is connection
    options = connect.call_args.kwargs["options"]
    assert "-csearch_path=clock_schema" in options and "-clock_timeout=5000" in options
    assert options.endswith("-ctimezone=UTC")
    connection.execute.assert_not_called()
    connection.commit.assert_not_called()


def test_private_clock_probe_is_bounded_and_does_not_close_a_borrowed_transaction(authority, monkeypatch):
    cursor = ClockCursor(authority)
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    connect = Mock(return_value=nullcontext(connection))
    monkeypatch.setattr(domain_module.psycopg, "connect", connect)
    assert authority.canonical_now() == INSTANT
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert connect.call_args.kwargs["options"].endswith("-cstatement_timeout=5000")
    connect.reset_mock()
    authority._transaction_connection = connection
    assert authority.canonical_now() == INSTANT
    connect.assert_not_called()
    connection.commit.assert_not_called()
    connection.close.assert_not_called()


def test_authorization_uses_database_time_with_host_clock_unavailable(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    cursor = ClockCursor(authority)
    authority._authorize(command(authority), cursor, "work_item.create", "local-scope")
    assert sum(statement == "SELECT clock_timestamp()" for statement, _ in cursor.statements) >= 3
    assert any("g.expires_at>clock_timestamp()" in statement for statement, _ in cursor.statements)


@pytest.mark.parametrize("expired", ["grant", "deadline"])
def test_authorization_refreshes_database_time_after_grant_lock_wait(authority, monkeypatch, expired):
    forbid_host_clock(monkeypatch)
    until = INSTANT + timedelta(seconds=2)
    cursor = ClockCursor(authority, grant_expiry=until if expired == "grant" else None,
                         after_grant_lock=until + timedelta(seconds=1))
    submitted = command(authority, deadline=until if expired == "deadline" else INSTANT + timedelta(minutes=5))
    with pytest.raises(AuthorizationDenied):
        authority._authorize(submitted, cursor, "work_item.create", "local-scope")


def test_delegated_grant_expiry_uses_database_time(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    cursor = ClockCursor(authority, grant_expiry=INSTANT - timedelta(seconds=1))
    with pytest.raises(AuthorizationDenied):
        authority._authorize_delegation(cursor, command(authority), "work_item.create")


def test_database_clock_preserves_the_existing_explicit_skew_bound(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    future = command(authority, issued_at=INSTANT + timedelta(seconds=2))
    with pytest.raises(AuthorizationDenied):
        authority._authorize(future, ClockCursor(authority), "work_item.create")
    authority._authorize(future, ClockCursor(authority), "work_item.create", clock_skew_seconds=5)
    with pytest.raises(AuthorizationDenied):
        authority._authorize(future, ClockCursor(authority), "work_item.create", clock_skew_seconds=31)


def test_lease_internal_read_command_is_minted_from_transaction_time(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    cursor = ClockCursor(authority)
    read = authority.leases._read_command("resource-clock", "effect.read", cursor)
    assert read.issued_at == INSTANT
    assert read.deadline == INSTANT + timedelta(minutes=5)
    assert cursor.statements == [("SELECT clock_timestamp()", ())]


def test_future_execution_observation_is_rejected_against_database_time(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    receipt = SimpleNamespace(is_complete=True, readback_refs=("readback",),
                              observed_at=INSTANT + timedelta(seconds=1))
    with pytest.raises(AcceptanceGuardFailed, match="complete successful"):
        authority._validate_execution_receipt(receipt, "local-scope", cursor=ClockCursor(authority))


def test_expired_bundle_is_rejected_against_database_time(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    monkeypatch.setattr(authority, "_typed_evidence", lambda _model, value, _label: value)
    receipt = SimpleNamespace(is_complete=True, observed_at=INSTANT - timedelta(seconds=2))
    bundle = SimpleNamespace(is_complete=True, execution_receipt=receipt,
        observed_at=INSTANT - timedelta(seconds=1), expires_at=INSTANT - timedelta(seconds=1))
    evidence = SimpleNamespace(evidence_state="complete", source_class="directly_verified")
    with pytest.raises(AcceptanceGuardFailed, match="complete typed"):
        authority._validate_bundle(ClockCursor(authority), evidence, bundle,
                                   "work-clock", "baseline", "local-scope")


def receiver_fixture(authority, cursor, monkeypatch):
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(authority, "_connect", lambda: nullcontext(connection))
    monkeypatch.setattr(authority, "_authorize", Mock())
    monkeypatch.setattr(authority, "_dedup", Mock(return_value=(None, "digest")))
    return ReceiverTransportAuthority(authority)


@pytest.mark.parametrize("registration", ["key", "connection"])
def test_receiver_registration_expiry_uses_database_time(authority, monkeypatch, registration):
    forbid_host_clock(monkeypatch)
    cursor = ClockCursor(authority)
    receiver = receiver_fixture(authority, cursor, monkeypatch)
    if registration == "key":
        request = AuthorityTransportKeyRegistration(key_id="key-clock", revision=1,
            public_key=SigningKey.generate().verify_key.encode().hex(),
            expires_at=INSTANT - timedelta(seconds=1))
        submitted = command(authority, command_type="receiver.key.register",
                            target_kind="authority_transport_key", target_id=request.key_id)
        operation = receiver.register_authority_key
    else:
        request = ConnectionReferenceRegistration(connection_ref="connection-clock", revision=1,
            locator_host="127.0.0.1", locator_port=443, route_class="loopback",
            policy_digest="a" * 64, expires_at=INSTANT - timedelta(seconds=1))
        submitted = command(authority, command_type="receiver.connection.register",
                            target_kind="connection", target_id=request.connection_ref)
        operation = receiver.register_connection
    with pytest.raises(AcceptanceGuardFailed, match="expired"):
        operation(submitted, request)
    assert not any(statement.startswith("INSERT") for statement, _ in cursor.statements)


def test_receiver_key_expiry_is_rechecked_after_retirement_locks(authority, monkeypatch):
    forbid_host_clock(monkeypatch)
    cursor = ClockCursor(authority)
    cursor.on_retire = INSTANT + timedelta(seconds=3)
    receiver = receiver_fixture(authority, cursor, monkeypatch)
    request = AuthorityTransportKeyRegistration(key_id="key-clock", revision=1,
        public_key=SigningKey.generate().verify_key.encode().hex(),
        expires_at=INSTANT + timedelta(seconds=2))
    submitted = command(authority, command_type="receiver.key.register",
                        target_kind="authority_transport_key", target_id=request.key_id)
    with pytest.raises(AcceptanceGuardFailed, match="expired"):
        receiver.register_authority_key(submitted, request)
    assert not any(statement.startswith("INSERT") for statement, _ in cursor.statements)


@pytest.mark.parametrize("expired", ["endpoint", "authority-key"])
def test_receiver_current_authority_rechecks_bindings_after_locks(authority, monkeypatch, expired):
    forbid_host_clock(monkeypatch)
    submitted = command(authority)
    admission = SimpleNamespace(
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        tenant_id=authority.context.tenant_id, message_id="message-clock", operation_id="operation-clock",
        endpoint_id="endpoint-clock", endpoint_revision=1, authority_key_id="key-clock", authority_key_revision=1,
        runtime_id="runtime-clock", runtime_revision=1, node_id="node-clock", machine_id="machine-clock",
        boot_incarnation="boot-clock", scope_id="local-scope", agent_slot_id="local-slot",
        purpose="delivery.dispatch", deadline=INSTANT + timedelta(minutes=1),
    )

    class CurrentAuthorityCursor(ClockCursor):
        def fetchone(self):
            if self.statement.startswith("SELECT m.command_json"):
                endpoint_expiry = INSTANT + timedelta(seconds=2 if expired == "endpoint" else 60)
                key_expiry = INSTANT + timedelta(seconds=2 if expired == "authority-key" else 60)
                return (submitted.model_dump(mode="json"), admission.endpoint_revision,
                        admission.runtime_id, admission.runtime_revision, admission.node_id,
                        admission.machine_id, admission.boot_incarnation, admission.scope_id,
                        admission.agent_slot_id, endpoint_expiry, key_expiry)
            return super().fetchone()

    cursor = CurrentAuthorityCursor(authority)
    receiver = receiver_fixture(authority, cursor, monkeypatch)
    authority._authorize.side_effect = lambda *_args, **_kwargs: setattr(
        cursor, "now", INSTANT + timedelta(seconds=3),
    )
    assert receiver.current_authority(admission) is False


@pytest.fixture
def postgres_authority(request):
    domain = DomainAuthority(request.getfixturevalue("isolated_dsn"))
    domain.initialize()
    domain.bootstrap_local_grant()
    return domain


def test_postgres_clock_refreshes_inside_one_utc_transaction(postgres_authority):
    authority = postgres_authority
    with authority._connect() as connection:
        assert connection.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        assert connection.execute("SHOW TimeZone").fetchone()[0] == "UTC"
        assert "ledger_test_" in connection.execute("SHOW search_path").fetchone()[0]
        with connection.cursor() as cursor:
            before = authority.canonical_now(cursor)
            cursor.execute("SELECT pg_sleep(0.03)")
            after = authority.canonical_now(cursor)
        assert after > before and before.tzinfo is UTC and after.tzinfo is UTC


def test_postgres_expired_grant_denies_even_when_application_clock_is_behind(postgres_authority, monkeypatch):
    authority = postgres_authority
    now = authority.canonical_now()
    submitted = command(authority, issued_at=now - timedelta(seconds=1), deadline=now + timedelta(minutes=5))
    with authority._connect() as connection:
        connection.execute("UPDATE grants SET expires_at=clock_timestamp()-interval '10 seconds' "
                           "WHERE grant_ref=%s", (authority.context.grant_ref,))
    forbid_host_clock(monkeypatch)
    with (
        authority._connect() as connection, connection.cursor() as cursor,
        pytest.raises(AuthorizationDenied),
    ):
        authority._authorize(submitted, cursor, "work_item.create", "local-scope")


def test_postgres_internal_work_item_read_survives_application_clock_loss(postgres_authority, monkeypatch):
    authority = postgres_authority
    now = authority.canonical_now()
    submitted = command(authority, issued_at=now - timedelta(seconds=1), deadline=now + timedelta(minutes=5))
    authority.create_work_item(submitted, "local-scope", "local-slot", "clock-baseline")
    forbid_host_clock(monkeypatch)
    assert authority.get_work_item(submitted.target_id)["source_baseline"] == "clock-baseline"



def bridge_command(*, expires_at=INSTANT + timedelta(minutes=5)):
    return IncidentOpenCommand(
        "incident-clock", 1, "tenant", "message", "operation", "source", "target", 7,
        "a" * 64, expires_at, ("native",),
        (RecoveryPath("native", "failed", ("attempt-ref",), ("evidence-ref",)),), "command-clock",
    )


def bridge_authority_snapshot(*, deadline=INSTANT + timedelta(minutes=5)):
    return BridgeAuthoritySnapshot(True, True, True, True, 7, "a" * 64, deadline,
                                   "agent:manager", "grant:bridge", "policy-clock")


class BridgeCursor:
    def __init__(self, *, now=INSTANT, after_lock=None, prior=None):
        self.now, self.after_lock, self.prior = now, after_lock, prior
        self.statements, self.statement = [], ""

    def execute(self, statement, parameters=()):
        self.statement = statement
        self.statements.append((statement, parameters))
        if statement.startswith("SELECT canonical_digest") and self.after_lock is not None:
            self.now = self.after_lock

    def fetchone(self):
        if self.statement == "SELECT clock_timestamp()":
            return (self.now,)
        if self.statement.startswith("SELECT canonical_digest"):
            return self.prior
        raise AssertionError("unexpected incident fixture query: " + self.statement)


def bridge_unit(monkeypatch, cursor, snapshot):
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(psycopg, "connect", lambda _dsn: nullcontext(connection))
    monkeypatch.setattr(recovery_module, "datetime", HostClockMustNotBeUsed)
    return PostgresHumanBridgeAuthority("fixture-clock", snapshot)


def test_bridge_open_uses_utc_database_time_and_preserves_valid_replay(monkeypatch):
    submitted = bridge_command()
    cursor = BridgeCursor(now=INSTANT.astimezone(timezone(timedelta(hours=9))),
                          prior=(canonical_digest(submitted.canonical()),))
    snapshots = Mock(return_value=bridge_authority_snapshot())
    authority = bridge_unit(monkeypatch, cursor, snapshots)
    assert authority.open_incident(submitted) == "open"
    assert [call.args[1] for call in snapshots.call_args_list] == ["incident.open", "incident.open.final"]
    assert sum(sql == "SELECT clock_timestamp()" for sql, _ in cursor.statements) == 2
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


@pytest.mark.parametrize("expired", ["incident", "authority"])
def test_bridge_open_rechecks_expiry_after_incident_lock(monkeypatch, expired):
    submitted = bridge_command(expires_at=INSTANT + timedelta(seconds=2 if expired == "incident" else 60))
    snapshot = bridge_authority_snapshot(deadline=INSTANT + timedelta(seconds=2 if expired == "authority" else 60))
    cursor = BridgeCursor(after_lock=INSTANT + timedelta(seconds=3))
    authority = bridge_unit(monkeypatch, cursor, lambda *_args: snapshot)
    with pytest.raises(BoundaryRejected, match="final authority"):
        authority.open_incident(submitted)
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_bridge_open_denies_authority_deadline_even_before_incident_expiry(monkeypatch):
    cursor = BridgeCursor()
    snapshot = bridge_authority_snapshot(deadline=INSTANT - timedelta(seconds=1))
    authority = bridge_unit(monkeypatch, cursor, lambda *_args: snapshot)
    with pytest.raises(BoundaryRejected, match="deadline expired"):
        authority.open_incident(bridge_command())
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_bridge_open_rechecks_current_authority_after_lock(monkeypatch):
    cursor = BridgeCursor()
    snapshots = Mock(side_effect=[bridge_authority_snapshot(),
                                 replace(bridge_authority_snapshot(), current_authority_valid=False)])
    authority = bridge_unit(monkeypatch, cursor, snapshots)
    with pytest.raises(BoundaryRejected, match="final authority"):
        authority.open_incident(bridge_command())
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


@pytest.mark.parametrize("after_fail", [False, True])
def test_immediate_projection_stays_pending_after_host_backstep(tmp_path, monkeypatch, after_fail):
    outbox = NodeResponseOutbox(tmp_path / "responses.sqlite")
    item = response_observation()
    assert outbox.record(item)
    if after_fail:
        outbox.fail(item.projection_id, "temporary_failure")

    class BehindClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(days=1)

    monkeypatch.setattr(recovery_module, "datetime", BehindClock)
    assert outbox.pending() == (item,)
    assert NodeResponseOutbox(outbox.path).pending() == (item,)


def test_projection_queue_order_survives_wall_clock_backstep(tmp_path, monkeypatch):
    outbox = NodeResponseOutbox(tmp_path / "responses.sqlite")
    first = response_observation(projection_id="first", native_response_ref="native-first")
    second = response_observation(
        projection_id="second", native_response_ref="native-second",
        identity=response_identity(message_id="message-second", invocation_id="invocation-second"),
    )
    assert outbox.record(first)

    class BehindClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(days=1)

    monkeypatch.setattr(recovery_module, "datetime", BehindClock)
    assert outbox.record(second)
    assert outbox.pending() == (first, second)
    assert [item["projection_id"] for item in outbox.recover()] == ["first", "second"]


@pytest.mark.parametrize("shift,expired", [(1, False), (-1, True)])
def test_postgres_bridge_open_is_independent_of_application_clock(request, monkeypatch, shift, expired):
    dsn = request.getfixturevalue("recovery_postgres_dsn")
    seed_message(dsn)
    with psycopg.connect(dsn) as connection:
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    submitted = bridge_command(expires_at=now + timedelta(seconds=-1 if expired else 60))
    snapshot = bridge_authority_snapshot(deadline=now + timedelta(minutes=5))
    authority = PostgresHumanBridgeAuthority(dsn, lambda *_args: snapshot)

    class ShiftedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=shift)

    monkeypatch.setattr(recovery_module, "datetime", ShiftedClock)
    if expired:
        with pytest.raises(BoundaryRejected):
            authority.open_incident(submitted)
        expected = 0
    else:
        assert authority.open_incident(submitted) == "open"
        assert authority.open_incident(submitted) == "open"
        expected = 1
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM recovery_incidents").fetchone() == (expected,)

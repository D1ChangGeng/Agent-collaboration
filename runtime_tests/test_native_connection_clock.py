"""Native timing boundaries with synthetic transports and calibrated Authority UTC."""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from runtime import codex_driver, delivery_node, native_delivery, opencode_driver
from runtime.codex_driver import AuthorizedOperation, DriverJournal, DriverRejected
from runtime.connection_clock import ConnectionClock
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import DeliveryBoundaryRejected, LocalNodeEndpoint, invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.recovery_models import BoundaryRejected, canonical_digest
from runtime.response_collector import NativeResponseCollector
from runtime_tests import test_codex_driver as codex_tests
from runtime_tests import test_opencode_driver as opencode_tests


class Timeline:
    def __init__(self, year=2020):
        self.anchor = datetime(year, 1, 1, tzinfo=UTC)
        self.elapsed = 0.0
        self.wall = datetime(2060, 1, 1, tzinfo=UTC)
        self.available = True
        self.clock = ConnectionClock(
            "domain:authority:incarnation", self.reference,
            identity={"authority_id": "authority", "authority_incarnation": "incarnation"},
            monotonic=lambda: self.elapsed, wall=lambda: self.wall,
        )

    def reference(self):
        if not self.available:
            raise OSError("Authority reference unavailable")
        return self.anchor + timedelta(seconds=self.elapsed)

    def operation(self, label, seconds=20):
        return AuthorizedOperation(label, "cmd-" + label, "msg-" + label, "grant",
                                   self.clock.now() + timedelta(seconds=seconds))


class NoHostWall(datetime):
    @classmethod
    def now(cls, tz=None):
        raise AssertionError("native timing read the host wall clock")


@pytest.fixture(params=["codex", "opencode"])
def native_clock(request, tmp_path, monkeypatch):
    module = codex_tests if request.param == "codex" else opencode_tests
    profile = module.profile.__wrapped__(tmp_path)
    iterator = (module.native.__wrapped__(tmp_path, profile, monkeypatch)
                if request.param == "codex" else module.native.__wrapped__(tmp_path, profile))
    native = next(iterator)
    previous = native.driver
    previous.detach_transport()
    timeline = Timeline()
    driver = type(previous)(
        previous.binding_id, previous.profile, previous.journal,
        identity=previous.identity, check_current=previous.check_current,
        supervisor=previous.supervisor, clock=timeline.clock,
    )
    native.driver = driver
    for source in (codex_driver, opencode_driver, native_delivery, delivery_node):
        monkeypatch.setattr(source, "datetime", NoHostWall)
    try:
        yield native, timeline
    finally:
        if driver.owned is not None and driver.owned.process.poll() is None:
            driver.supervisor.terminate_tree(driver.owned)
        driver.detach_transport()
        with pytest.raises(StopIteration):
            next(iterator)


def envelope(clock, identity=None, *, seconds=20):
    node, boot, slot = (identity.node_id, identity.node_boot_id, identity.agent_slot_id) if identity else ("node", "boot", "slot")
    packet = DeliveryPacket(
        work_item_id="work", target_scope_id="scope", target_agent_slot_id=slot,
        accepted_revision=0, goal="timed delivery", accepted_state_summary="accepted",
        request="bounded native work", source_baseline="baseline", expected_response="response",
        activation="invoke", delivery_policy="queue_until_idle",
        deadline=clock.now() + timedelta(seconds=seconds),
    )
    return DeliveryEnvelope(
        tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        principal_ref="principal", grant_ref="grant", message_id="message",
        command_id="command", operation_id="operation", endpoint_id="endpoint",
        binding_revision=1, machine_id="machine", node_id=node, boot_incarnation=boot,
        accepted_state_digest="a" * 64, packet=packet,
    )


@pytest.mark.parametrize("year", [2020, 2099])
def test_authorized_operation_uses_authority_and_monotonic_remaining(year):
    timeline = Timeline(year)
    operation = timeline.operation("bounded")
    operation.validate(timeline.clock)
    initial = operation.remaining(timeline.clock)
    timeline.elapsed = 4
    timeline.wall += timedelta(days=30000)
    assert operation.remaining(timeline.clock) == pytest.approx(initial - 4, abs=0.002)
    timeline.wall -= timedelta(days=50000)
    operation.validate(timeline.clock)
    assert set(asdict(operation)) == {"operation_id", "command_id", "message_id", "grant_ref", "deadline"}
    timeline.elapsed = 20
    with pytest.raises(DriverRejected):
        operation.validate(timeline.clock)


def test_operation_refuses_unavailable_or_uncertain_authority_reference():
    timeline = Timeline()
    operation = timeline.operation("closed")
    timeline.elapsed = 31
    timeline.available = False
    with pytest.raises(DriverRejected):
        operation.remaining(timeline.clock)
    uncertain = ConnectionClock(
        "slow-authority", lambda: datetime(2020, 1, 1, tzinfo=UTC),
        monotonic=iter([0, 5]).__next__, wall=lambda: datetime(2020, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(DriverRejected):
        operation.validate(uncertain)


def test_journal_validates_clock_after_obtaining_write_transaction(tmp_path):
    timeline = Timeline()
    journal = DriverJournal(tmp_path / "driver.sqlite", clock=timeline.clock)
    operation = timeline.operation("journal", seconds=1)
    timeline.elapsed = 2
    with pytest.raises(DriverRejected):
        journal.begin(operation, "binding", "invoke", {})
    assert journal.read(operation.operation_id) is None


def test_native_driver_and_idle_lease_survive_wall_jumps(native_clock):
    native, timeline = native_clock
    driver = native.driver
    driver.spawn(timeline.operation("spawn"))
    value = envelope(timeline.clock, driver.identity)
    invocation = invocation_for(value, "attempt")
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda request, identity: AuthorizedOperation(
        request.invocation_id, request.command_id, request.message_id,
        request.envelope.grant_ref, request.envelope.packet.deadline,
    ), clock=timeline.clock)
    readiness = adapter.readiness(invocation)
    assert readiness["activity"] == "idle" and readiness["clock"]["canonical_utc"].startswith("2020-")
    assert not any("monotonic" in key for key in readiness["clock"])
    timeline.wall += timedelta(days=10000)
    assert adapter._readiness_fresh(readiness)
    timeline.clock.invalidate()
    assert not adapter._readiness_fresh(readiness)
    readiness = adapter.readiness(invocation)
    timeline.elapsed = 2
    timeline.wall -= timedelta(days=20000)
    assert not adapter._readiness_fresh(readiness)
    adapter.prepare(invocation)
    observed = adapter.invoke(invocation, on_dispatch=lambda: None)
    assert observed.native_ack_ref is not None
    assert driver.journal.read(invocation.invocation_id)["result"]["observed_at"].startswith("2020-")
    timeline.elapsed = 21
    with pytest.raises(DriverRejected):
        driver.inspect(timeline.operation("expired", seconds=-1))


def test_node_clock_preserves_trusted_authorizer_and_rejects_other_authority(tmp_path, monkeypatch):
    timeline = Timeline()
    monkeypatch.setattr(delivery_node, "datetime", NoHostWall)
    journal = NodeJournal(tmp_path / "node.sqlite", machine_id="machine", node_id="node", boot_incarnation="boot")
    endpoint = LocalNodeEndpoint(journal, "scope", "slot", clock=timeline.clock)
    value = envelope(timeline.clock)
    calls = []
    endpoint._commit_inbox(value, lambda: calls.append(True) or value)
    assert len(calls) == 2
    with journal._transaction() as connection:
        observed = connection.execute("SELECT observed_at FROM lifecycle_receipts").fetchall()
    assert observed and all(row[0].startswith("2020-") for row in observed)
    with pytest.raises(DeliveryBoundaryRejected, match="authorization_reference"):
        endpoint._check(value, lambda: value.model_copy(update={"grant_ref": "other"}))
    endpoint.clock = ConnectionClock(
        "domain:authority:other", timeline.reference,
        identity={"authority_id": "authority", "authority_incarnation": "other"},
        monotonic=lambda: timeline.elapsed,
    )
    with pytest.raises(DeliveryBoundaryRejected, match="clock_authority"):
        endpoint._check(value, lambda: value)


def test_naive_terminal_timestamp_is_rejected_before_outbox_write(native_clock, tmp_path):
    native, timeline = native_clock
    driver = native.driver
    driver.spawn(timeline.operation("spawn"))
    invocation = invocation_for(envelope(timeline.clock, driver.identity), "attempt")
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda request, identity: AuthorizedOperation(
        request.invocation_id, request.command_id, request.message_id,
        request.envelope.grant_ref, request.envelope.packet.deadline,
    ), clock=timeline.clock)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    if driver.harness == "opencode":
        native.peer.finish()
    else:
        native.state["turns"][0]["status"] = "completed"
    collect = driver.collect_result

    def terminal(*args):
        return {**collect(*args), "native_terminal_observed_at": "2020-01-01T00:00:00"}

    driver.collect_result = terminal
    node = NodeJournal(tmp_path / "response.sqlite", machine_id="machine", node_id=driver.identity.node_id,
                       boot_incarnation=driver.identity.node_boot_id)
    stored = []
    collector = NativeResponseCollector(adapter, node.response_outbox(),
        lambda result: (stored.append(result) or "artifact", canonical_digest(result)), lambda observation: None)
    with pytest.raises(BoundaryRejected, match="timestamp"):
        collector._collect(invocation)
    assert stored == []
    assert collector.outbox.by_invocation(collector.dispatch_identity(invocation)) is None
    driver.collect_result = lambda *args: {**collect(*args), "native_terminal_observed_at": "2020-01-01T09:00:00+09:00"}
    observed = collector._collect(invocation)
    assert observed.observed_at == datetime(2020, 1, 1, tzinfo=UTC)


def test_production_domain_rechecks_use_canonical_authority_without_skew():
    from types import SimpleNamespace

    from runtime_deployment.receiver_codex import CodexReceiverCapacity
    seen = []
    capacity = object.__new__(CodexReceiverCapacity)
    capacity.clock = Timeline().clock
    capacity.config = SimpleNamespace(clock_skew_seconds=5)
    capacity.authority = SimpleNamespace(
        _authorize=lambda *args, **kwargs: seen.append(kwargs),
        receiver_transport=SimpleNamespace(current_authority=lambda *args, **kwargs: seen.append(kwargs) or True),
    )
    capacity._authorize_domain_command(object(), object(), "runtime.invoke", "scope")
    assert capacity.authorize_current(object())
    assert seen == [{"clock_skew_seconds": 0}, {"clock_skew_seconds": 0}]


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_native_timeout_preserves_before_and_after_dispatch_state(native_clock, monkeypatch, after_dispatch):
    from runtime.codex_jsonrpc import RpcPreCallTimeout, RpcTimeout
    from runtime.opencode_http import HttpPreCallTimeout

    native, timeline = native_clock
    driver = native.driver
    driver.spawn(timeline.operation("spawn-timeout"))
    original = driver.client.request
    dispatched = []

    def request(method, target, *args, **kwargs):
        mutation = method == "turn/start" if driver.harness == "codex" else method == "POST" and target.endswith("/prompt_async")
        if not mutation:
            return original(method, target, *args, **kwargs)
        if after_dispatch:
            kwargs["on_dispatch"]()
            raise RpcTimeout("after native marker") if driver.harness == "codex" else TimeoutError("after native marker")
        raise RpcPreCallTimeout("before native marker") if driver.harness == "codex" else HttpPreCallTimeout("before native marker")

    monkeypatch.setattr(driver.client, "request", request)
    operation = timeline.operation("timed-out")
    expected = (RpcTimeout if driver.harness == "codex" else TimeoutError) if after_dispatch else DriverRejected
    with pytest.raises(expected):
        driver.invoke(operation, "timed request", on_dispatch=lambda: dispatched.append(True))
    assert driver.journal.read(operation.operation_id)["state"] == ("uncertain" if after_dispatch else "rejected")
    assert dispatched == ([True] if after_dispatch else [])
    if driver.harness == "codex":
        assert driver._turn_start_attempted is after_dispatch
    if not after_dispatch:
        monkeypatch.setattr(driver.client, "request", original)
        receipt = driver.invoke(timeline.operation("fresh-after-timeout"), "fresh authorized request", on_dispatch=lambda: None)
        assert receipt["receipt_layer"] == "runtime_acknowledged"



def test_native_readiness_ttl_consumes_producer_uncertainty(native_clock):
    native, timeline = native_clock

    def sampled_at_receive():
        timeline.elapsed += 1
        return timeline.reference()

    producer = ConnectionClock(
        "domain:authority:incarnation", sampled_at_receive,
        identity={"authority_id": "authority", "authority_incarnation": "incarnation"},
        monotonic=lambda: timeline.elapsed,
        wall=timeline.reference,
    )
    timeline.clock = producer
    native.driver.clock = native.driver.journal.clock = producer
    native.driver.spawn(timeline.operation("asymmetric-spawn", seconds=180))
    invocation = invocation_for(envelope(producer, native.driver.identity, seconds=180), "attempt")
    adapter = NativeDeliveryAdapter(native.driver, authorize_invocation=lambda request, identity: AuthorizedOperation(
        request.invocation_id, request.command_id, request.message_id,
        request.envelope.grant_ref, request.envelope.packet.deadline,
    ), clock=producer)
    observed = adapter.readiness(invocation)
    assert observed["clock"]["uncertainty_seconds"] == pytest.approx(0.5, abs=0.001)
    timeline.elapsed += 2.2
    consumer = ConnectionClock(
        "domain:authority:incarnation", timeline.reference,
        identity=producer.identity, monotonic=lambda: timeline.elapsed, wall=timeline.reference,
    )
    issued = datetime.fromisoformat(observed["observed_at"])
    expiry = datetime.fromisoformat(observed["expires_at"])
    assert not consumer.fresh(issued, expiry, max_lifetime=2)



def test_native_fact_timestamps_use_fresh_reference_under_high_rtt(native_clock):
    native, timeline = native_clock

    def reference_at_receive():
        timeline.elapsed += 0.6
        return timeline.reference()

    clock = ConnectionClock(
        "domain:authority:incarnation", reference_at_receive,
        identity={"authority_id": "authority", "authority_incarnation": "incarnation"},
        monotonic=lambda: timeline.elapsed, wall=timeline.reference,
    )
    timeline.clock = clock
    native.driver.clock = native.driver.journal.clock = clock
    registered_at = timeline.reference()
    spawned = native.driver.spawn(timeline.operation("fact-spawn", seconds=180))
    assert registered_at <= datetime.fromisoformat(spawned["observed_at"]) <= timeline.reference()
    execution_start = timeline.reference()
    operation = timeline.operation("fact-invoke", seconds=180)
    invoked = native.driver.invoke(operation, "bounded fact request", on_dispatch=lambda: None)
    assert execution_start <= datetime.fromisoformat(invoked["observed_at"]) <= timeline.reference()
    with native.driver.journal._connect() as connection:
        times = connection.execute("SELECT observed_at FROM driver_events WHERE operation_id=?",
                                   (operation.operation_id,)).fetchall()
    assert times and all(execution_start <= datetime.fromisoformat(row[0]) <= timeline.reference() for row in times)
    if native.driver.harness == "opencode":
        native.peer.finish()
    else:
        native.state["turns"][0]["status"] = "completed"
    terminal = native.driver.collect_result(operation, operation.operation_id)
    first_terminal = terminal["native_terminal_observed_at"]
    assert execution_start <= datetime.fromisoformat(first_terminal) <= timeline.reference()
    repeated = native.driver.collect_result(operation, operation.operation_id)
    assert repeated["native_terminal_observed_at"] == first_terminal


def test_readiness_fact_timestamp_accepts_low_uncertainty_consumer(native_clock, monkeypatch):
    native, timeline = native_clock
    native.driver.spawn(timeline.operation("ready-fact-spawn"))

    def reference_at_receive():
        timeline.elapsed += 0.6
        return timeline.reference()

    producer = ConnectionClock(
        "domain:authority:incarnation", reference_at_receive,
        identity={"authority_id": "authority", "authority_incarnation": "incarnation"},
        monotonic=lambda: timeline.elapsed, wall=timeline.reference,
    )
    timeline.clock = producer
    native.driver.clock = native.driver.journal.clock = producer
    value = envelope(producer, native.driver.identity, seconds=180)
    invocation = invocation_for(value, "attempt")
    adapter = NativeDeliveryAdapter(native.driver, authorize_invocation=lambda request, identity: AuthorizedOperation(
        request.invocation_id, request.command_id, request.message_id,
        request.envelope.grant_ref, request.envelope.packet.deadline,
    ), clock=producer)
    # Isolate observation stamping from the independently tested native readback
    # transport; the real bound Driver and kernel claim remain in use.
    state = {"thread": {"status": {"type": "idle"}}, "turns": []} if native.driver.harness == "codex" else {"status": {"type": "idle"}}
    monkeypatch.setattr(native.driver, "inspect", lambda operation: state)
    observed_before = producer.reading().earliest_utc
    result = adapter.readiness(invocation)
    issued = datetime.fromisoformat(result["observed_at"])
    expiry = datetime.fromisoformat(result["expires_at"])
    assert observed_before <= issued <= timeline.reference()
    assert expiry <= observed_before + timedelta(seconds=2)
    consumer = ConnectionClock(
        "domain:authority:incarnation", timeline.reference,
        identity=producer.identity, monotonic=lambda: timeline.elapsed, wall=timeline.reference,
    )
    assert consumer.fresh(issued, expiry, max_lifetime=2)
    timeline.elapsed += 2.2
    assert not consumer.fresh(issued, expiry, max_lifetime=2)

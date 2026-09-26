"""Formal NativeDeliveryAdapter to Node response Outbox integration."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from runtime.codex_driver import AuthorizedOperation
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.recovery import NodeResponseOutbox, ProjectionDisposition
from runtime.recovery_models import canonical_digest
from runtime.response_collector import NativeResponseCollector
from runtime_tests.test_opencode_driver import native as native  # noqa: PLC0414
from runtime_tests.test_opencode_driver import operation, prompts
from runtime_tests.test_opencode_driver import profile as profile  # noqa: PLC0414

DIGEST = "a" * 64


def invocation_for_native(native):
    identity = native.driver.identity
    packet = DeliveryPacket(
        work_item_id="work",
        target_scope_id="scope",
        target_agent_slot_id=identity.agent_slot_id,
        accepted_revision=7,
        goal="Collect the delayed response",
        accepted_state_summary="accepted state",
        request="return one response",
        source_baseline="baseline",
        expected_response="one terminal response",
        activation="invoke",
        deadline=datetime.now(UTC) + timedelta(minutes=2),
    )
    envelope = DeliveryEnvelope(
        tenant_id="tenant",
        authority_id="authority",
        authority_incarnation="incarnation",
        principal_ref="agent",
        grant_ref="grant",
        message_id="packet-invoke",
        command_id="cmd-invoke",
        operation_id="delivery-operation",
        endpoint_id="endpoint",
        binding_revision=identity.revision,
        machine_id="machine",
        node_id=identity.node_id,
        boot_incarnation=identity.node_boot_id,
        accepted_state_digest=DIGEST,
        packet=packet,
    )
    return invocation_for(envelope, identity.attempt_id)


def test_delayed_opencode_response_is_collected_once_and_projection_only_retries(
    native, tmp_path,
):
    native.driver.spawn(operation("spawn"))
    invocation = invocation_for_native(native)

    def authorize(value, binding):
        assert binding == native.driver.identity
        return AuthorizedOperation(
            value.invocation_id,
            value.command_id,
            value.message_id,
            value.envelope.grant_ref,
            value.envelope.packet.deadline,
        )

    adapter = NativeDeliveryAdapter(native.driver, authorize_invocation=authorize)
    first = adapter.invoke(invocation, on_dispatch=lambda: None)
    assert first.native_ack_ref is not None
    assert len(prompts(native.peer)) == 1
    native.peer.finish()

    journal = NodeJournal(
        tmp_path / "node.sqlite",
        machine_id="machine",
        node_id=native.driver.identity.node_id,
        boot_incarnation=native.driver.identity.node_boot_id,
    )
    outbox = journal.response_outbox()
    collect_calls = 0
    original_collect = native.driver.collect_result

    def counted_collect(*args, **kwargs):
        nonlocal collect_calls
        collect_calls += 1
        return original_collect(*args, **kwargs)

    native.driver.collect_result = counted_collect
    projected = []

    def store(value):
        return "artifact:" + canonical_digest(value), canonical_digest(value)

    def project(observation):
        projected.append(observation.projection_id)
        return ProjectionDisposition(
            observation.projection_id,
            NodeResponseOutbox._payload(observation)[1],
            "applied",
        )

    collector = NativeResponseCollector(adapter, outbox, store, project)
    first_projection = collector.collect_and_project(invocation)
    second_projection = collector.collect_and_project(invocation)
    assert first_projection == second_projection
    assert collect_calls == 1
    assert len(prompts(native.peer)) == 1
    assert projected == [first_projection.projection_id, first_projection.projection_id]
    assert outbox.recover() == ()

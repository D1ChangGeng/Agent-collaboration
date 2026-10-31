"""Historical projection assertions from the retired execution surface.

Retained as v6 research evidence; this is not a current receiver capability.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import invocation_for
from runtime.response_collector import NativeResponseCollector
from runtime_deployment.receiver_codex import CodexReceiverCapacity, CodexReceiverRejected


def test_projection_identity_adopts_only_a_newer_recovery_binding():
    envelope = DeliveryEnvelope(
        tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        principal_ref="sender", grant_ref="grant", message_id="message",
        command_id="command", operation_id="operation", endpoint_id="endpoint",
        binding_revision=1, machine_id="machine", node_id="node",
        boot_incarnation="boot-1", accepted_state_digest="a" * 64,
        packet=DeliveryPacket(
            work_item_id="work", target_scope_id="scope", target_agent_slot_id="slot",
            accepted_revision=0, goal="Recover projection", accepted_state_summary="fixture",
            request="observe current binding", source_baseline="fixture",
            expected_response="done", activation="invoke",
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        ),
    )
    recorded = invocation_for(envelope, "attempt")
    old = NativeResponseCollector.dispatch_identity(recorded)
    current = old.__class__(
        **{**old.__dict__, "binding_revision": 2, "boot_incarnation": "boot-2"}
    )
    recovery = SimpleNamespace(admission=SimpleNamespace(
        purpose="delivery.recover", tenant_id=old.tenant_id,
        message_id=old.message_id, operation_id=old.operation_id,
        attempt_id=old.attempt_id, dispatch_id=old.dispatch_id,
        endpoint_id=old.endpoint_id, endpoint_revision=2,
        runtime_id="runtime-2", runtime_revision=1,
        machine_id=old.machine_id, node_id=old.node_id,
        boot_incarnation="boot-2", scope_id="scope", agent_slot_id="slot",
    ))
    endpoint = (
        old.endpoint_id, 2, "runtime-2", 1, old.machine_id, old.node_id,
        "boot-2", "scope", "slot",
    )
    assert CodexReceiverCapacity._current_dispatch_identity(
        recorded, current, endpoint, recovery,
    ) == current
    ordinary_dispatch = SimpleNamespace(admission=SimpleNamespace(
        purpose="delivery.dispatch", tenant_id=old.tenant_id,
        message_id=old.message_id, operation_id=old.operation_id,
        attempt_id=old.attempt_id, dispatch_id=old.dispatch_id,
        endpoint_id=old.endpoint_id, endpoint_revision=1,
        runtime_id="runtime-1", runtime_revision=1,
        machine_id=old.machine_id, node_id=old.node_id,
        boot_incarnation=old.boot_incarnation,
        scope_id="scope", agent_slot_id="slot",
    ))
    assert CodexReceiverCapacity._current_dispatch_identity(
        recorded, old,
        (old.endpoint_id, 1, "runtime-1", 1, old.machine_id, old.node_id,
         old.boot_incarnation, "scope", "slot"),
        ordinary_dispatch,
    ) == old
    with pytest.raises(CodexReceiverRejected, match="binding differs"):
        CodexReceiverCapacity._current_dispatch_identity(
            recorded, old.__class__(**{**old.__dict__, "node_id": "changed"}),
            (old.endpoint_id, 1, "runtime-1", 1, old.machine_id, old.node_id,
             old.boot_incarnation, "scope", "slot"),
            SimpleNamespace(admission=SimpleNamespace(
                purpose="delivery.dispatch", tenant_id=old.tenant_id,
                message_id=old.message_id, operation_id=old.operation_id,
                attempt_id=old.attempt_id, dispatch_id=old.dispatch_id,
                endpoint_id=old.endpoint_id, endpoint_revision=1,
                runtime_id="runtime-1", runtime_revision=1,
                machine_id=old.machine_id, node_id=old.node_id,
                boot_incarnation=old.boot_incarnation,
                scope_id="scope", agent_slot_id="slot",
            )),
        )
    for field in ("endpoint_id", "machine_id", "node_id", "boot_incarnation"):
        changed = old.__class__(**{
            **current.__dict__, field: "changed",
        })
        with pytest.raises(CodexReceiverRejected):
            CodexReceiverCapacity._current_dispatch_identity(
                recorded, changed, endpoint, recovery,
            )
    with pytest.raises(CodexReceiverRejected, match="dispatch revision differs"):
        CodexReceiverCapacity._current_dispatch_identity(
            recorded, current, endpoint,
            SimpleNamespace(admission=SimpleNamespace(**{
                **recovery.admission.__dict__, "purpose": "delivery.dispatch",
            })),
        )

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from runtime.recovery_models import (
    BoundaryRejected,
    DelayedResponseProjector,
    DeliveryProjection,
    DispatchIdentity,
    HumanBridgeCoordinator,
    IncidentState,
    ManualPacket,
    NativeResponseObservation,
    NormalReceipt,
    ProjectionState,
    RecoveryPath,
    StateConflict,
    response_receipt_id,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
DIGEST = "a" * 64


def identity(**changes):
    value = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt-1", "dispatch-1",
        "endpoint", 4, "machine", "node", "boot", 7, DIGEST,
    )
    return replace(value, **changes)


def delivery(**changes):
    value = DeliveryProjection(identity(), NOW + timedelta(minutes=5), "attempt-1", 7, DIGEST)
    for key, item in changes.items():
        setattr(value, key, item)
    return value


def observation(**changes):
    dispatch = changes.get("identity", identity())
    projection_id = changes.get("projection_id", "projection-1")
    value = NativeResponseObservation(
        projection_id, response_receipt_id(dispatch, projection_id), dispatch,
        "native-response-1", "completed",
        "artifact:response-1", "c" * 64, "b" * 64, NOW,
    )
    return replace(value, **changes)


def paths():
    return (
        RecoveryPath("native-reconnect", "failed", ("attempt-a",), ("evidence-a",)),
        RecoveryPath("provider-switch", "budget_exhausted", ("attempt-b",), ("evidence-b",)),
    )


def incident(coordinator):
    return coordinator.open_incident(
        incident_id="incident-1", generation=3, tenant_id="tenant", message_id="message",
        operation_id="operation", source_scope_id="source", target_scope_id="target",
        accepted_revision=7, accepted_state_digest=DIGEST,
        expires_at=NOW + timedelta(minutes=10), eligible_path_ids=("native-reconnect", "provider-switch"),
        paths=paths(), now=NOW, task_valid=True, current_authority_valid=True,
    )


def packet(**changes):
    value = ManualPacket(
        "packet-1", "incident-1", 3, "tenant", "message", "operation", "attempt-1",
        "dispatch-1", "source", "target", "response", 7, DIGEST, "c" * 64,
        NOW + timedelta(minutes=5),
    )
    return replace(value, **changes)


def normal_receipt(for_packet=None, **changes):
    value_packet = for_packet or packet()
    value = NormalReceipt(
        "normal-receipt-1",
        "target_inbox_committed" if value_packet.direction == "request" else "response_received",
        "tenant", "message", "operation", "incident-1", 3, value_packet.packet_id,
        value_packet.attempt_id, value_packet.dispatch_id, value_packet.direction,
        value_packet.payload_digest, "d" * 64,
    )
    return replace(value, **changes)


class DelayedResponseTests(unittest.TestCase):
    def test_delayed_response_advances_exact_original_dispatch(self):
        target = delivery()
        result = DelayedResponseProjector().project(
            target, observation(), now=NOW + timedelta(seconds=1), producer_authenticated=True,
            current_authority_valid=True,
        )
        self.assertEqual(result, ProjectionState.APPLIED)
        self.assertEqual(target.receipt_high_water, "response_received")

    def test_projection_replay_is_idempotent(self):
        target = delivery()
        projector = DelayedResponseProjector()
        first = projector.project(target, observation(), now=NOW, producer_authenticated=True,
                                  current_authority_valid=True)
        second = projector.project(target, observation(), now=NOW, producer_authenticated=True,
                                   current_authority_valid=True)
        self.assertEqual((first, second), (ProjectionState.APPLIED, ProjectionState.APPLIED))
        self.assertEqual(len(target.observations), 1)

    def test_projection_identity_reuse_conflicts(self):
        target = delivery()
        projector = DelayedResponseProjector()
        projector.project(target, observation(), now=NOW, producer_authenticated=True,
                          current_authority_valid=True)
        with self.assertRaises(StateConflict):
            projector.project(
                target, observation(evidence_digest="d" * 64), now=NOW, producer_authenticated=True,
                current_authority_valid=True,
            )

    def test_wrong_dispatch_identity_is_rejected(self):
        with self.assertRaises(BoundaryRejected):
            DelayedResponseProjector().project(
                delivery(), observation(identity=identity(dispatch_id="wrong")),
                now=NOW, producer_authenticated=True, current_authority_valid=True,
            )

    def test_replaced_attempt_is_audited_but_fenced(self):
        target = delivery(current_attempt_id="attempt-2")
        result = DelayedResponseProjector().project(
            target, observation(), now=NOW, producer_authenticated=True,
            current_authority_valid=True,
        )
        self.assertEqual(result, ProjectionState.FENCED_LATE)
        self.assertNotIn("response_received", target.receipts)

    def test_fenced_old_attempt_does_not_block_current_attempt_receipt(self):
        projector = DelayedResponseProjector()
        old = delivery(current_attempt_id="attempt-2")
        old_observation = observation()
        self.assertEqual(projector.project(
            old, old_observation, now=NOW, producer_authenticated=True,
            current_authority_valid=True,
        ), ProjectionState.FENCED_LATE)
        current_identity = identity(attempt_id="attempt-2", invocation_id="invocation-2",
                                    dispatch_id="dispatch-2")
        current = DeliveryProjection(
            current_identity, NOW + timedelta(minutes=5), "attempt-2", 7, DIGEST,
        )
        current_observation = observation(
            projection_id="projection-2", identity=current_identity,
            native_response_ref="native-response-2",
        )
        self.assertNotEqual(old_observation.receipt_id, current_observation.receipt_id)
        self.assertEqual(projector.project(
            current, current_observation, now=NOW, producer_authenticated=True,
            current_authority_valid=True,
        ), ProjectionState.APPLIED)

    def test_expired_or_revoked_receipt_cannot_advance(self):
        for target, now, valid in (
            (delivery(), NOW + timedelta(minutes=6), True),
            (delivery(), NOW, False),
            (delivery(current_accepted_revision=8), NOW, True),
        ):
            with self.subTest(target=target.current_accepted_revision, valid=valid):
                self.assertEqual(
                    DelayedResponseProjector().project(
                        target, observation(), now=now, producer_authenticated=True,
                        current_authority_valid=valid,
                    ),
                    ProjectionState.FENCED_LATE,
                )

    def test_unauthenticated_producer_is_rejected_without_consuming_identity(self):
        target = delivery()
        projector = DelayedResponseProjector()
        with self.assertRaises(BoundaryRejected):
            projector.project(target, observation(), now=NOW, producer_authenticated=False,
                              current_authority_valid=True)
        self.assertEqual(projector.project(
            target, observation(), now=NOW, producer_authenticated=True,
            current_authority_valid=True,
        ), ProjectionState.APPLIED)

    def test_response_receipt_conflict_is_atomic(self):
        target = delivery()
        target.receipts["response_received"] = {"receipt_id": "different"}
        projector = DelayedResponseProjector()
        with self.assertRaises(StateConflict):
            projector.project(target, observation(), now=NOW, producer_authenticated=True,
                              current_authority_valid=True)
        self.assertEqual(target.observations, {})
        self.assertEqual(projector._native_refs, {})
        self.assertEqual(projector._invocation_terminals, {})
        self.assertEqual(projector._projection_ids, {})
        self.assertEqual(projector._receipt_ids, {})
        self.assertEqual(target.receipt_high_water, "runtime_dispatched")

    def test_receipt_id_conflict_and_duplicate_terminal_do_not_pollute(self):
        projector = DelayedResponseProjector()
        first = delivery()
        projector.project(first, observation(), now=NOW, producer_authenticated=True,
                          current_authority_valid=True)
        second_identity = identity(message_id="message-2", operation_id="operation-2",
                                   invocation_id="invocation-2", attempt_id="attempt-2",
                                   dispatch_id="dispatch-2")
        second = DeliveryProjection(
            second_identity, NOW + timedelta(minutes=5), "attempt-2", 7, DIGEST,
        )
        with self.assertRaises(BoundaryRejected):
            projector.project(
                second,
                observation(projection_id="projection-2", identity=second_identity,
                            native_response_ref="native-response-2",
                            receipt_id=observation().receipt_id),
                now=NOW, producer_authenticated=True, current_authority_valid=True,
            )
        self.assertEqual(second.observations, {})
        self.assertEqual(second.receipts, {})

        third = delivery()
        with self.assertRaises(StateConflict):
            projector.project(
                third,
                observation(projection_id="projection-3", native_outcome="failed"),
                now=NOW, producer_authenticated=True, current_authority_valid=True,
            )
        self.assertEqual(third.observations, {})
        self.assertEqual(third.receipts, {})

    def test_native_response_ref_is_scoped_by_invocation(self):
        projector = DelayedResponseProjector()
        projector.project(delivery(), observation(), now=NOW, producer_authenticated=True,
                          current_authority_valid=True)
        second_identity = identity(message_id="message-2", operation_id="operation-2",
                                   invocation_id="invocation-2", attempt_id="attempt-2",
                                   dispatch_id="dispatch-2")
        second = DeliveryProjection(
            second_identity, NOW + timedelta(minutes=5), "attempt-2", 7, DIGEST,
        )
        self.assertEqual(projector.project(
            second,
            observation(projection_id="projection-2", identity=second_identity),
            now=NOW, producer_authenticated=True, current_authority_valid=True,
        ), ProjectionState.APPLIED)


class HumanBridgeTests(unittest.TestCase):
    def test_bridge_requires_complete_proven_exhaustion(self):
        with self.assertRaises(BoundaryRejected):
            HumanBridgeCoordinator().open_incident(
                incident_id="incident", generation=1, tenant_id="tenant", message_id="message",
                operation_id="operation", source_scope_id="source", target_scope_id="target",
                accepted_revision=7, accepted_state_digest=DIGEST, expires_at=NOW + timedelta(minutes=1),
                eligible_path_ids=("native-reconnect", "provider-switch", "missing"), paths=paths(),
                now=NOW, task_valid=True, current_authority_valid=True,
            )

    def test_request_is_idempotent_and_identity_conflict_fails(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        self.assertEqual(coordinator.request_human(value, request_id="request-1", now=NOW,
                                                   send_authorized=True), "request-1")
        self.assertEqual(coordinator.request_human(value, request_id="request-1", now=NOW,
                                                   send_authorized=True), "request-1")
        with self.assertRaises(StateConflict):
            coordinator.request_human(value, request_id="request-2", now=NOW, send_authorized=True)

    def test_successful_reprobe_resolves_automatic_and_fences_manual_packet(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
        self.assertEqual(coordinator.reprobe_succeeded(value, observation_ref="probe", now=NOW),
                         IncidentState.RESOLVED_AUTOMATIC)
        self.assertEqual(
            coordinator.submit_manual(
                value, packet(), now=NOW, authenticated_subject=True,
                current_authority_valid=True, task_valid=True, current_accepted_revision=7,
                current_accepted_state_digest=DIGEST,
            ),
            "fenced_late",
        )

    def test_valid_manual_packet_resolves_only_after_normal_receipt(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
        self.assertEqual(coordinator.submit_manual(
            value, packet(), now=NOW, authenticated_subject=True, current_authority_valid=True,
            task_valid=True, current_accepted_revision=7, current_accepted_state_digest=DIGEST,
        ), "committed")
        self.assertEqual(value.state, IncidentState.MANUAL_PACKET_COMMITTED)
        self.assertEqual(coordinator.confirm_manual_delivery(
            value, packet_id="packet-1", receipt=normal_receipt()),
            IncidentState.RESOLVED_MANUAL)
        self.assertEqual(coordinator.confirm_manual_delivery(
            value, packet_id="packet-1", receipt=normal_receipt()),
            IncidentState.RESOLVED_MANUAL)

    def test_manual_packet_replay_and_conflict(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
        args = {"now": NOW, "authenticated_subject": True, "current_authority_valid": True,
                "task_valid": True, "current_accepted_revision": 7,
                "current_accepted_state_digest": DIGEST}
        self.assertEqual(coordinator.submit_manual(value, packet(), **args), "committed")
        self.assertEqual(coordinator.submit_manual(value, packet(), **args), "committed")
        with self.assertRaises(StateConflict):
            coordinator.submit_manual(value, packet(payload_digest="e" * 64), **args)

    def test_expired_revoked_or_wrong_generation_packet_is_fenced_or_rejected(self):
        for current, valid, task_valid, revision in (
            (NOW + timedelta(minutes=11), True, True, 7),
            (NOW, False, True, 7),
            (NOW, True, False, 7),
            (NOW, True, True, 8),
        ):
            coordinator = HumanBridgeCoordinator()
            value = incident(coordinator)
            coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
            self.assertEqual(coordinator.submit_manual(
                value, packet(packet_id=f"packet-{current}-{valid}-{task_valid}-{revision}"), now=current,
                authenticated_subject=True, current_authority_valid=valid, task_valid=task_valid,
                current_accepted_revision=revision, current_accepted_state_digest=DIGEST,
            ), "fenced_late")
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
        self.assertEqual(coordinator.submit_manual(
            value, packet(incident_generation=2), now=NOW, authenticated_subject=True,
            current_authority_valid=True, task_valid=True, current_accepted_revision=7,
            current_accepted_state_digest=DIGEST,
        ), "fenced_late")

    def test_cross_tenant_or_incident_manual_packet_is_rejected(self):
        for changed in (packet(tenant_id="other"), packet(incident_id="other")):
            coordinator = HumanBridgeCoordinator()
            value = incident(coordinator)
            coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
            with self.assertRaises(BoundaryRejected):
                coordinator.submit_manual(
                    value, changed, now=NOW, authenticated_subject=True,
                    current_authority_valid=True, task_valid=True, current_accepted_revision=7,
                    current_accepted_state_digest=DIGEST,
                )

    def test_expiry_is_deterministic_and_idempotent(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        self.assertEqual(coordinator.expire(value, now=NOW + timedelta(minutes=11)),
                         IncidentState.EXPIRED)
        self.assertEqual(coordinator.expire(value, now=NOW + timedelta(minutes=12)),
                         IncidentState.EXPIRED)

    def test_unauthenticated_manual_packet_is_rejected_without_consuming_id(self):
        coordinator = HumanBridgeCoordinator()
        value = incident(coordinator)
        coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
        args = {"now": NOW, "current_authority_valid": True, "task_valid": True,
                "current_accepted_revision": 7, "current_accepted_state_digest": DIGEST}
        with self.assertRaises(BoundaryRejected):
            coordinator.submit_manual(value, packet(), authenticated_subject=False, **args)
        self.assertEqual(coordinator.submit_manual(
            value, packet(), authenticated_subject=True, **args,
        ), "committed")

    def test_confirm_binds_direction_receipt_digest_and_original_lineage(self):
        for direction, expected_layer in (
            ("request", "target_inbox_committed"), ("response", "response_received"),
        ):
            coordinator = HumanBridgeCoordinator()
            value = incident(coordinator)
            coordinator.request_human(value, request_id="request", now=NOW, send_authorized=True)
            manual = packet(direction=direction, packet_id=f"packet-{direction}")
            coordinator.submit_manual(
                value, manual, now=NOW, authenticated_subject=True,
                current_authority_valid=True, task_valid=True, current_accepted_revision=7,
                current_accepted_state_digest=DIGEST,
            )
            wrong_layer = "response_received" if direction == "request" else "target_inbox_committed"
            with self.assertRaises(BoundaryRejected):
                coordinator.confirm_manual_delivery(
                    value, packet_id=manual.packet_id,
                    receipt=normal_receipt(
                        manual, receipt_id=f"wrong-{direction}", layer=wrong_layer,
                    ),
                )
            with self.assertRaises(BoundaryRejected):
                coordinator.confirm_manual_delivery(
                    value, packet_id=manual.packet_id,
                    receipt=normal_receipt(
                        manual, receipt_id=f"wrong-lineage-{direction}", operation_id="other",
                    ),
                )
            for field, changed in (
                ("packet_id", "other"), ("payload_digest", "e" * 64),
                ("attempt_id", "other"), ("dispatch_id", "other"),
                ("direction", "request" if direction == "response" else "response"),
            ):
                with self.subTest(direction=direction, field=field), self.assertRaises(
                    BoundaryRejected
                ):
                    coordinator.confirm_manual_delivery(
                        value, packet_id=manual.packet_id,
                        receipt=normal_receipt(
                            manual, receipt_id=f"wrong-{field}-{direction}", **{field: changed},
                        ),
                    )
            self.assertEqual(coordinator.confirm_manual_delivery(
                value, packet_id=manual.packet_id,
                receipt=normal_receipt(
                    manual, receipt_id=f"normal-{direction}", layer=expected_layer,
                ),
            ), IncidentState.RESOLVED_MANUAL)

    def test_open_rejects_duplicate_paths_and_unbounded_input(self):
        duplicate = (
            RecoveryPath("same", "failed", ("attempt-a",), ("evidence-a",)),
            RecoveryPath("same", "failed", ("attempt-b",), ("evidence-b",)),
        )
        coordinator = HumanBridgeCoordinator()
        with self.assertRaises(BoundaryRejected):
            coordinator.open_incident(
                incident_id="incident", generation=1, tenant_id="tenant", message_id="message",
                operation_id="operation", source_scope_id="source", target_scope_id="target",
                accepted_revision=7, accepted_state_digest=DIGEST,
                expires_at=NOW + timedelta(minutes=1), eligible_path_ids=("same", "same"),
                paths=duplicate, now=NOW, task_valid=True, current_authority_valid=True,
            )
        with self.assertRaises(BoundaryRejected):
            coordinator.open_incident(
                incident_id="x" * 513, generation=1, tenant_id="tenant", message_id="message",
                operation_id="operation", source_scope_id="source", target_scope_id="target",
                accepted_revision=7, accepted_state_digest=DIGEST,
                expires_at=NOW + timedelta(minutes=1), eligible_path_ids=("native-reconnect",),
                paths=(paths()[0],), now=NOW, task_valid=True, current_authority_valid=True,
            )

    def test_incident_open_is_idempotent_and_spec_conflict_fails(self):
        coordinator = HumanBridgeCoordinator()
        first = incident(coordinator)
        self.assertIs(incident(coordinator), first)
        with self.assertRaises(StateConflict):
            coordinator.open_incident(
                incident_id="incident-1", generation=4, tenant_id="tenant",
                message_id="message", operation_id="operation", source_scope_id="source",
                target_scope_id="target", accepted_revision=7,
                accepted_state_digest=DIGEST, expires_at=NOW + timedelta(minutes=10),
                eligible_path_ids=("native-reconnect", "provider-switch"), paths=paths(),
                now=NOW, task_valid=True, current_authority_valid=True,
            )


if __name__ == "__main__":
    unittest.main()

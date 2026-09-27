"""Shared formal enrollment for regression fixtures.

Only existing Scope/Grant bootstrap is fixture setup. Node, Runtime and Attempt
records are created through the real Domain APIs with real Ed25519 signatures.
Source/provider/start observations remain explicitly test-fixture metadata; this
helper is not an OS containment or Harness-conformance measurement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    AttemptRegistration,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    RuntimeRegistration,
)
from runtime.models import CommandEnvelope


def enrollment_command(domain, action, target_kind, target_id, revision=0):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return CommandEnvelope(
        command_id=f"fixture-enrollment-command-{identity}", idempotency_key=f"fixture-enrollment-key-{identity}",
        command_type=action, correlation_id="formal-enrollment-fixture", tenant_id=domain.tenant_id,
        authority_id=domain.context.authority_id, authority_incarnation=domain.context.authority_incarnation,
        principal_ref=domain.context.principal_ref, grant_ref=domain.context.grant_ref,
        target_kind=target_kind, target_id=target_id, expected_revision=revision,
        issued_at=now, deadline=now + timedelta(minutes=10),
    )


@dataclass
class EnrolledFixture:
    operator: Any
    node: Any
    node_id: str
    key: Ed25519PrivateKey = field(repr=False)
    runtime_id: str = ""
    attempt_id: str = ""
    attempt: dict[str, Any] = field(default_factory=dict)
    node_revision: int = 1

    def sign(self, command, node_input):
        # Challenge issuance is a real audited command. Negative tests call this
        # before taking their ledger baseline or introducing their fault.
        challenge = self.node.challenge_node(
            enrollment_command(self.node, "node.challenge", "node", self.node_id, self.node_revision),
            NodeChallengeRequest(purpose=command.command_type, purpose_command_id=command.command_id,
                purpose_hash=EnrollmentAuthority.signing_hash(command, node_input), ttl_seconds=300),
        )
        return NodeCommandProof(challenge_id=challenge.challenge_id,
                                signature=self.key.sign(bytes.fromhex(challenge.message_hex)).hex())

    def receipt_proof(self, command, receipt):
        return self.sign(command, {"receipt": receipt.model_dump(mode="json")})


def register_execution_fixture(
    producer, *, work_item_id, runtime_id, attempt_id, node=None, operator=None, node_id=None,
    provider="fixture-node", source_commit="fixture-commit", source_tree="fixture-tree",
    candidate_ref="fixture-candidate",
):
    """Provision one valid signed binding, without modifying existing authority.

    Runtime identity requires the producer's valid scoped Grant, not unrelated
    evidence/invoke/publish capabilities. This function never adds permissions
    to that producer or rewrites a production guard.
    """
    node_id = node_id or f"fixture-node-{attempt_id}"
    store = getattr(producer, "_artifact_store", None)
    cls = type(producer)
    if operator is None:
        operator = cls(producer._dsn, context=replace(producer.context,
            principal_ref=f"fixture-operator:{node_id}", grant_ref=f"grant:fixture-operator:{node_id}"), artifact_store=store)
        operator.bootstrap_local_grant(("enrollment.manage", "work_item.read"))
    if node is None:
        node = cls(producer._dsn, context=replace(producer.context,
            principal_ref=f"fixture-observer:{node_id}", grant_ref=f"grant:fixture-observer:{node_id}"), artifact_store=store)
        node.bootstrap_local_grant(("runtime.register", "attempt.register", "execution.record", "work_item.read"))
    with producer._connect() as conn:
        work = conn.execute("SELECT scope_id,agent_slot_id,source_baseline,revision FROM work_items "
                            "WHERE tenant_id=%s AND work_item_id=%s", (producer.tenant_id, work_item_id)).fetchone()
    if work is None:
        raise AssertionError("fixture WorkItem must already exist")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    enrolled = EnrolledFixture(operator, node, node_id, private, runtime_id, attempt_id)
    operator.enroll_node(enrollment_command(operator, "node.enroll", "node", node_id), NodeEnrollment(
        scope_id=work[0], agent_slot_id=work[1], observer_grant_ref=node.context.grant_ref,
        machine_id=f"fixture-machine:{node_id}", boot_incarnation=f"fixture-boot-{uuid.uuid4()}",
        public_key=public, expires_at=datetime.now(UTC) + timedelta(hours=2)))
    runtime_request = RuntimeRegistration(node_id=node_id, node_binding_revision=1, provider=provider,
        producer_grant_ref=producer.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(hours=1))
    runtime_command = enrollment_command(node, "runtime.register", "runtime", runtime_id)
    node.register_runtime(runtime_command, runtime_request,
                          enrolled.sign(runtime_command, {"request": runtime_request.model_dump(mode="json")}))
    attempt_request = AttemptRegistration(runtime_id=runtime_id, work_item_id=work_item_id,
        expected_work_item_revision=int(work[3]), source_baseline=work[2], source_commit=source_commit,
        source_tree=source_tree, candidate_ref=candidate_ref, observed_started_at=datetime.now(UTC))
    attempt_command = enrollment_command(node, "attempt.register", "attempt", attempt_id)
    reply = node.register_attempt(attempt_command, attempt_request,
                                  enrolled.sign(attempt_command, {"request": attempt_request.model_dump(mode="json")}))
    enrolled.attempt = reply.binding
    return enrolled


def raw_ledger_counts(domain):
    with domain._connect() as conn:
        return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("command_dedup", "domain_events", "operations", "outbox"))

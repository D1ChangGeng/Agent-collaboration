"""Durable original-session reconstruction, with controlled Native stop facts."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import AuthorizedOperation, CodexAppServerDriver, DriverRejected
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_capacity import (
    CapacityEvidenceUnavailable,
    recover_capacity_profile,
)
from runtime.receiver_lifecycle_contract import (
    LifecycleChallenge,
    LifecyclePermit,
    build_lifecycle_plan,
    lifecycle_plan_digest,
    sign_challenge,
    sign_permit,
)
from runtime.receiver_lifecycle_node import ReceiverLifecycleNode
from runtime_tests.test_receiver_cold_restore import controlled_transport
from runtime_tests.test_receiver_lifecycle_capacity import capacity as capacity_fixture
from runtime_tests.test_receiver_lifecycle_node import node as node_fixture

capacity = capacity_fixture
node = node_fixture


def stopped_journal(node):
    node.prepare("spawn")
    created = node.execute().receipt
    original_permit = node.permit
    old = node.driver
    if old.client is not None:
        old.client.close = lambda: None

    def stop(owned):
        assert owned is old.owned
        owned.process.poll = lambda: 0
        node.capacity.proof.update(root_exited=True, remaining_pids=[])
        return dict(node.capacity.proof)

    old.supervisor.terminate_tree = stop
    close = AuthorizedOperation("controlled-real-stop", "controlled-close-command", "technical-close-source",
        "trusted-stop-grant", node.driver_time.now + timedelta(minutes=1))
    assert type(old).terminate(old, close)["receipt_layer"] == "process_tree_terminated"
    node.controller.close()
    old.journal.release_claim(old._claim_token)
    current = type(old)(old.binding_id, old.profile, old.journal, identity=old.identity,
        check_current=lambda *_args: None, supervisor=SimpleNamespace(inspect=lambda _owned: dict(node.capacity.proof),
            launch=lambda *_args, **_kw: pytest.fail("profile reconstruction cannot launch")), clock=node.clock)
    return old, current, created, original_permit


def test_reconstructed_node_uses_core_attested_profile_and_original_stop_without_native_contact(node, monkeypatch):
    old, driver, created, original_permit = stopped_journal(node)
    before = list(node.native_calls)
    attestations = []

    def original(origin, seal):
        attestations.append(origin)
        assert origin.creation_operation_id == original_permit.permit.plan.driver_operation_id
        assert origin.command_id == original_permit.permit.plan.source.command_id
        assert seal["profile_fingerprint"] == original_permit.permit.plan.capacity.profile_fingerprint

    witness = recover_capacity_profile(driver, authorize_current=lambda actual: None,
        account_fingerprint=lambda actual: node.capacity.account, authorize_original=original)
    assert len(attestations) == 1 and node.native_calls == before
    assert driver.owned is driver.client is None and driver.ownership == "exclusive_reserved_restore"
    assert (getattr(driver, "thread_id", None) or driver.session_id) == created.native_session_ref
    node.source = node.source.model_copy(update={"operation_ref": "after-node-reconstruction", "command_id": "after-node-command"})
    restored = ReceiverLifecycleNode(driver, node.config, node.node_key, clock=node.clock, resolve_original=node.resolve,
        require_current_execution=node.require, resolve_original_read=node.read, profile_witness=witness)
    node.driver = driver
    starts = controlled_transport(node, monkeypatch)
    try:
        raw = LifecycleChallenge(source=node.source, target=node.snapshot.target(), authority_key_id=node.config.authority_key_id,
            authority_key_revision=node.config.authority_key_revision, request_id="durable-restore-request", nonce="a" * 64,
            issued_at=node.driver_time.now, deadline=node.driver_time.now + timedelta(seconds=20))
        challenge = sign_challenge(raw, node.key)
        observation = restored.observe(challenge)
        assert observation.observation.capacity.state == "stopped"
        assert observation.observation.capacity.ownership == "exclusive_reserved"
        plan = build_lifecycle_plan(raw, observation.observation, "resume")
        permit = LifecyclePermit(plan=plan, semantic_digest=lifecycle_plan_digest(plan), challenge_digest=sha256(raw),
            observation_digest=sha256(observation.observation), authority_key_id=node.config.authority_key_id,
            authority_key_revision=node.config.authority_key_revision, request_id=raw.request_id, nonce=raw.nonce,
            issued_at=node.driver_time.now, deadline=node.driver_time.now + timedelta(seconds=10))
        node.permit = sign_permit(permit, node.key)
        receipt = restored.execute(node.permit, challenge=challenge, observation=observation).receipt
        assert receipt.outcome == "acknowledged" and receipt.native_session_ref == created.native_session_ref, (
            restored._last_rejection, driver.journal.read(plan.driver_operation_id))
        assert len(starts) == 1
        assert not any(m == "turn/start" or m == "POST" and "prompt" in p for m, p in node.native_calls)
    finally:
        restored.close()
        old.journal.release_claim(driver._claim_token)


@pytest.mark.parametrize("damage", ["missing_stop", "stop_survivors", "creation_unknown", "profile_attestation"])
def test_reconstruction_cannot_infer_missing_process_or_core_trust(node, damage):
    old, driver, _created, permit = stopped_journal(node)
    with driver.journal._connect() as connection:
        if damage == "missing_stop":
            connection.execute("DELETE FROM driver_operations WHERE action='terminate'")
        elif damage == "stop_survivors":
            connection.execute("UPDATE driver_operations SET result_json=json_set(result_json,'$.supervisor_proof.remaining_pids',json('[123]')) WHERE action='terminate'")
        elif damage == "creation_unknown":
            connection.execute("UPDATE driver_operations SET state='uncertain' WHERE operation_id=?", (permit.permit.plan.driver_operation_id,))

    def refused(_origin, _seal):
        raise CapacityEvidenceUnavailable("current_Core_attestation_refused")

    try:
        with pytest.raises((DriverRejected, CapacityEvidenceUnavailable)):
            recover_capacity_profile(driver, authorize_current=lambda _actual: None,
                account_fingerprint=lambda _actual: node.capacity.account,
                authorize_original=refused if damage == "profile_attestation" else lambda _origin, _seal: None)
        assert driver.client is driver.owned is None and driver.ownership == "unbound"
        assert driver.session_id is None and (not isinstance(driver, CodexAppServerDriver) or driver.thread_id is None)
    finally:
        old.journal.release_claim(driver._claim_token)

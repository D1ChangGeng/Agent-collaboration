from __future__ import annotations

import multiprocessing
import os
import sqlite3
from dataclasses import replace

import pytest

from runtime.receiver import ReceiverLedger, ReceiverService
from runtime.receiver_crypto import public_key, sign
from runtime.receiver_models import ReadbackBody, RecoveryBody
from runtime.remote_endpoint import RemoteNodeTransport, serve
from runtime_tests import test_receiver_protocol as protocol
from tools.runtime.p1_identity_continuity_probe import (
    AttemptReadback,
    ContinuityRejected,
    LogicalIdentity,
    NodeBootReadback,
    audit_component_chain,
    read_receiver_ledger,
    verify_signed_exchange,
)
from tools.runtime.p1_profile_probe import ScenarioCatalog

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="signed receiver runtime is POSIX-only",
)


def logical_attempt(env):
    registration = env.config.binding.registration
    logical = LogicalIdentity(
        tenant_id=env.node.tenant_id,
        authority_id=env.node.authority_id,
        authority_incarnation=env.node.authority_incarnation,
        work_item_id="work-one",
        scope_id=env.node.scope_id,
        agent_slot_id=env.node.agent_slot_id,
        machine_id=env.node.machine_id,
        node_id=env.node.node_id,
        message_id=env.identity.message_id,
        command_id=env.identity.command_id,
        operation_id=env.identity.operation_id,
        source_commit="1" * 40,
        source_tree="2" * 40,
        accepted_revision=env.identity.accepted_revision,
        accepted_state_digest=env.identity.accepted_state_digest,
        envelope_digest=env.identity.envelope_digest,
    )
    attempt = AttemptReadback(
        ordinal=1,
        tenant_id=logical.tenant_id,
        attempt_id=env.identity.attempt_id,
        dispatch_id=env.identity.dispatch_id,
        message_id=logical.message_id,
        command_id=logical.command_id,
        operation_id=logical.operation_id,
        work_item_id=logical.work_item_id,
        scope_id=logical.scope_id,
        agent_slot_id=logical.agent_slot_id,
        machine_id=logical.machine_id,
        node_id=logical.node_id,
        authority_id=logical.authority_id,
        authority_incarnation=logical.authority_incarnation,
        source_commit=logical.source_commit,
        source_tree=logical.source_tree,
        endpoint_id=registration.endpoint_id,
        endpoint_revision=registration.endpoint_revision,
        runtime_id=registration.runtime_id,
        runtime_revision=registration.runtime_revision,
        node_binding_revision=registration.node_binding_revision,
        boot_incarnation=registration.boot_incarnation,
        status="retry_wait",
    )
    return logical, attempt


def test_catalog_binds_identity_gate_to_formal_lineage():
    assert "P1-IDENTITY-CONTINUITY" in ScenarioCatalog.TESTS
    assert "P1-IDENTITY-CONTINUITY" in ScenarioCatalog.LINEAGE_BOUND


def observed_fixture(tmp_path):
    env = protocol.env.__wrapped__(tmp_path)
    service = protocol.service(env)
    request, receipt = protocol.prepare(env, service)
    logical, attempt = logical_attempt(env)
    return env, logical, attempt, request, receipt, service


def test_real_prepared_receiver_signature_binds_one_logical_attempt(tmp_path):
    env, logical, attempt, request, receipt, _service = observed_fixture(tmp_path)
    result = verify_signed_exchange(
        logical, attempt, env.config.binding, request, receipt,
        authority_public_key=public_key(env.authority_key),
    )
    assert result["state"] == "prepared"
    assert result["attempt_id"] == attempt.attempt_id
    assert result["machine_id"] == logical.machine_id
    assert result["source_commit"] == logical.source_commit


def test_receiver_prepare_dispatch_replay_stays_component_only(tmp_path):
    env, logical, attempt, prepare, prepared, service = observed_fixture(tmp_path)
    dispatch = protocol.dispatch_request(env, prepare)
    acknowledged = service.dispatch(dispatch, lambda _: {"ack": "actual"})
    readback_request = env.factory.request(
        "delivery.readback",
        ReadbackBody(operation_id=logical.operation_id, dispatch_id=attempt.dispatch_id),
    )
    readback_receipt = service.readback(readback_request)
    delivered = replace(attempt, status="delivered")
    boot = NodeBootReadback(
        binding_revision=env.registration.node_binding_revision,
        boot_incarnation=env.registration.boot_incarnation,
        machine_id=logical.machine_id, node_id=logical.node_id,
    )
    observations = (
        (delivered, env.config.binding, prepare, prepared),
        (delivered, env.config.binding, dispatch, acknowledged),
        (delivered, env.config.binding, dispatch, acknowledged),
        (delivered, env.config.binding, readback_request, readback_receipt),
    )
    result = audit_component_chain(
        logical, observations, (boot,),
        authority_public_key=public_key(env.authority_key),
        inbox_projection_ids=("inbox-one",),
        driver_dispatch_ids=(attempt.dispatch_id,),
        temporal_workflow_id="acs-delivery/" + logical.operation_id,
    )
    assert result["gate_status"] == "not_run"
    assert result["signed_exchange_count"] == 3
    assert result["inbox_projection_count"] == 1
    ledger = read_receiver_ledger(
        service.ledger, logical, allowed_attempt_ids=(attempt.attempt_id,),
    )
    assert ledger["native_dispatch_ids"] == [attempt.dispatch_id]
    with service.ledger.connect() as connection:
        connection.execute(
            "INSERT INTO native_calls(dispatch_id,request_id,called_at) VALUES (?,?,?)",
            ("unrelated-dispatch", "unrelated-request", "2026-09-13T00:00:00Z"),
        )
    assert read_receiver_ledger(
        service.ledger, logical, allowed_attempt_ids=(attempt.attempt_id,),
    )["native_dispatch_ids"] == [attempt.dispatch_id]
    with pytest.raises(ContinuityRejected, match="projected or dispatched twice"):
        audit_component_chain(
            logical, observations, (boot,),
            authority_public_key=public_key(env.authority_key),
            inbox_projection_ids=("inbox-one", "inbox-two"),
            driver_dispatch_ids=(attempt.dispatch_id,),
        )
    with pytest.raises(ContinuityRejected, match="Node boot readback"):
        audit_component_chain(
            logical, observations,
            (replace(boot, machine_id="forged-machine"),),
            authority_public_key=public_key(env.authority_key),
            inbox_projection_ids=("inbox-one",), driver_dispatch_ids=(),
        )
    changed_receipt = acknowledged.receipt.model_copy(
        update={"evidence": {**acknowledged.receipt.evidence, "changed": True}},
    )
    conflicting = acknowledged.model_copy(update={
        "receipt": changed_receipt,
        "signature": sign(env.node_key, changed_receipt),
    })
    with pytest.raises(ContinuityRejected, match="request replay changed"):
        audit_component_chain(
            logical, observations + (
                (delivered, env.config.binding, dispatch, conflicting),
            ),
            (boot,), authority_public_key=public_key(env.authority_key),
            inbox_projection_ids=("inbox-one",), driver_dispatch_ids=(),
        )


def test_actual_tls_two_process_receiver_feeds_signed_component(tmp_path):
    env = protocol.env.__wrapped__(tmp_path)
    logical, attempt = logical_attempt(env)
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    process = context.Process(
        target=serve,
        args=(
            env.config, ready, protocol.fixture_authority_current,
            protocol.fixture_native_invoke,
        ),
    )
    process.start()
    try:
        assert ready.wait(5) and process.is_alive() and process.pid != os.getpid()
        transport = RemoteNodeTransport(env.config)
        prepare = env.factory.request("delivery.prepare", env.prepare_body)
        prepared = transport.send(prepare)
        dispatch = protocol.dispatch_request(env, prepare)
        acknowledged = transport.send(dispatch)
        assert transport.send(dispatch) == acknowledged
        readback_request = env.factory.request(
            "delivery.readback",
            ReadbackBody(operation_id=logical.operation_id,
                         dispatch_id=attempt.dispatch_id),
        )
        readback_receipt = transport.send(readback_request)
        with sqlite3.connect(env.config.ledger_path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM native_calls"
            ).fetchone() == (1,)
        witness = ReceiverLedger(env.config.ledger_path)
        try:
            ledger_readback = read_receiver_ledger(
                witness, logical, allowed_attempt_ids=(attempt.attempt_id,),
            )
            assert ledger_readback["native_dispatch_ids"] == [attempt.dispatch_id]
        finally:
            witness.close()
        boot = NodeBootReadback(1, "boot-1", logical.machine_id, logical.node_id)
        delivered = replace(attempt, status="delivered")
        result = audit_component_chain(
            logical,
            (
                (delivered, env.config.binding, prepare, prepared),
                (delivered, env.config.binding, dispatch, acknowledged),
                (delivered, env.config.binding, dispatch, acknowledged),
                (delivered, env.config.binding, readback_request, readback_receipt),
            ),
            (boot,), authority_public_key=public_key(env.authority_key),
            inbox_projection_ids=(), driver_dispatch_ids=(attempt.dispatch_id,),
        )
        assert result["signed_exchange_count"] == 3
        assert result["gate_status"] == "not_run"
    finally:
        process.terminate()
        process.join(5)
    assert not process.is_alive()


def test_actual_second_boot_recovers_same_signed_attempt_once(tmp_path):
    env, logical, attempt, prepare, prepared, _old = observed_fixture(tmp_path)
    current = protocol.recovered_env(env, isolation_ref="old-boot-stopped")
    recovered = ReceiverService(
        current.config, env.node_key,
        authorize_current=protocol.fixture_authority_current,
    )
    recovered.claim_boot("boot-2", 2, old_boot_isolation_ref="old-boot-stopped")
    body = RecoveryBody(
        prepare_request_id=prepare.admission.request_id,
        marker_receipt_id="postgres-runtime-dispatched",
        old_boot_incarnation="boot-1", new_boot_incarnation="boot-2",
        journal_generation=2, old_boot_isolation_ref="old-boot-stopped",
        old_endpoint_revision=1, new_endpoint_revision=2,
        old_runtime_revision=1, new_runtime_revision=1,
    )
    request = current.factory.request(
        "delivery.recover", body, boot_incarnation="boot-2",
        journal_generation=2,
    )
    native_calls = []
    first = recovered.recover(
        request,
        lambda admission: native_calls.append(admission.dispatch_id)
        or {"ack": "recovered"},
    )
    assert recovered.recover(
        request, lambda _: native_calls.append("duplicate") or {},
    ) == first
    assert native_calls == [attempt.dispatch_id]
    old_boot = NodeBootReadback(1, "boot-1", logical.machine_id, logical.node_id)
    new_boot = NodeBootReadback(2, "boot-2", logical.machine_id, logical.node_id)
    result = audit_component_chain(
        logical,
        (
            (attempt, env.config.binding, prepare, prepared),
            (attempt, current.config.binding, request, first),
        ),
        (old_boot, new_boot),
        authority_public_key=public_key(env.authority_key),
        inbox_projection_ids=(),
        driver_dispatch_ids=(attempt.dispatch_id,),
    )
    assert result["gate_status"] == "not_run"
    assert result["boot_revisions"] == [1, 2]
    assert result["attempt_ids"] == [attempt.attempt_id]


@pytest.mark.parametrize("change", [
    "machine", "source", "authority", "body", "registration", "receipt_signature",
    "receipt_target", "receipt_id",
])
def test_signed_component_rejects_rebound_identity(tmp_path, change):
    env, logical, attempt, request, receipt, _service = observed_fixture(tmp_path)
    binding = env.config.binding
    if change == "machine":
        attempt = replace(attempt, machine_id="forged-machine")
    elif change == "source":
        attempt = replace(attempt, source_commit="f" * 40)
    elif change == "authority":
        altered = request.admission.model_copy(
            update={"authority_incarnation": "forged-incarnation"},
        )
        request = request.model_copy(update={
            "admission": altered,
            "signature": sign(env.authority_key, altered),
        })
    elif change == "body":
        request = request.model_copy(update={"body": {"changed": True}})
    elif change == "registration":
        altered = binding.registration.model_copy(
            update={"machine_id": "forged-machine"},
        )
        binding = binding.model_copy(update={
            "registration": altered,
            "registration_signature": sign(env.node_key, altered),
        })
    elif change == "receipt_target":
        changed = receipt.receipt.model_copy(update={"target_request_id": "wrong-request"})
        receipt = receipt.model_copy(update={
            "receipt": changed, "signature": sign(env.node_key, changed),
        })
    elif change == "receipt_id":
        changed = receipt.receipt.model_copy(update={"receipt_id": "wrong-receipt"})
        receipt = receipt.model_copy(update={
            "receipt": changed, "signature": sign(env.node_key, changed),
        })
    else:
        receipt = receipt.model_copy(update={"signature": "00" * 64})
    with pytest.raises(ContinuityRejected):
        verify_signed_exchange(
            logical, attempt, binding, request, receipt,
            authority_public_key=public_key(env.authority_key),
        )

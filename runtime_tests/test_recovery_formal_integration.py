"""Formal schema, Surface, projection and local Human Bridge integration."""
from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from runtime.delivery import digest
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import invocation_for
from runtime.domain import DomainAuthority
from runtime.errors import IdempotencyConflict
from runtime.human_bridge_dispatch import (
    HumanBridgeManualInbox,
    HumanBridgeProviderDispatcher,
    provision_local_provider,
)
from runtime.human_bridge_file_provider import ManualReturn, _canonical
from runtime.models import CommandEnvelope
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    NativeResponseObservation,
    canonical_digest,
    response_receipt_id,
)
from runtime.recovery_service import RecoveryService
from runtime.surfaces import SurfaceCommand
from runtime_tests.test_domain_ledger import isolated_dsn as isolated_dsn  # noqa: PLC0414

DIGEST = "a" * 64


def _process_recovery_submit(dsn, raw_command, payload, start, results):
    authority = DomainAuthority(dsn)
    submitted = CommandEnvelope.model_validate(raw_command)
    start.wait(timeout=10)
    try:
        result = RecoveryService(authority).execute(
            submitted, "recovery.incident.open", payload,
        )
        results.put(("result", result.state))
    except Exception as error:  # noqa: BLE001 - isolated process returns type only
        results.put(("error", type(error).__name__))


def command(authority, name, target, payload, *, kind="recovery", identity="one"):
    now = datetime.now(UTC)
    payload = json.loads(json.dumps(payload, default=lambda item: item.isoformat()))
    return CommandEnvelope(
        command_id=f"{name}:{identity}", idempotency_key=f"key:{name}:{identity}",
        correlation_id="recovery-integration", command_type=name,
        tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref,
        target_kind=kind, target_id=target, expected_revision=0,
        issued_at=now, deadline=now + timedelta(minutes=5), payload=payload,
    )


@pytest.fixture
def recovery_domain(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "delivery.project", "delivery.read", "delivery.consume",
        "recovery.manage", "recovery.read", "human_bridge.send", "human_bridge.receive",
    ))
    authority.create_work_item(
        command(
            authority, "work_item.create", "work", {
                "scope_id": "local-scope", "agent_slot_id": "local-slot",
                "source_baseline": "baseline",
            }, kind="work_item",
        ),
        "local-scope", "local-slot", "baseline",
    )
    now = datetime.now(UTC)
    packet = DeliveryPacket(
        work_item_id="work", target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="recover response", accepted_state_summary="revision zero",
        request="Reply with exactly ACS_P1_ASYNC_19_OK and no other text. Do not use tools.",
        source_baseline="baseline", expected_response="ACS_P1_ASYNC_19_OK",
        activation="invoke",
        deadline=now + timedelta(minutes=10),
    )
    envelope = DeliveryEnvelope(
        tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref,
        message_id="message", command_id="delivery-command", operation_id="delivery-operation",
        endpoint_id="endpoint", binding_revision=1, machine_id="machine", node_id="node",
        boot_incarnation="boot", accepted_state_digest=DIGEST, packet=packet,
    )
    invocation = invocation_for(envelope, "attempt")
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO enrolled_nodes(tenant_id,node_id,scope_id,agent_slot_id,observer_ref,"
            "observer_grant_ref,authority_id,authority_incarnation,revision,current_binding_revision,"
            "status,enrolled_by) VALUES (%s,'node','local-scope','local-slot','observer',%s,%s,%s,1,1,"
            "'active','fixture')",
            (authority.tenant_id, authority.context.grant_ref, authority.context.authority_id,
             authority.context.authority_incarnation),
        )
        connection.execute(
            "INSERT INTO enrolled_node_keys(key_id,tenant_id,node_id,public_key,fingerprint,status) "
            "VALUES ('node-key',%s,'node',%s,%s,'active')",
            (authority.tenant_id, "1" * 64, "2" * 64),
        )
        connection.execute(
            "INSERT INTO enrolled_node_bindings(tenant_id,node_id,binding_revision,key_id,machine_id,"
            "boot_incarnation,status,expires_at,command_id,operation_id) "
            "VALUES (%s,'node',1,'node-key','machine','boot','active',%s,'bind-command','bind-operation')",
            (authority.tenant_id, now + timedelta(minutes=10)),
        )
        connection.execute(
            "INSERT INTO delivery_endpoints(tenant_id,endpoint_id,revision,scope_id,agent_slot_id,"
            "machine_id,node_id,boot_incarnation,supports_invoke,evidence_class,expires_at,status,"
            "command_id,operation_id) VALUES (%s,'endpoint',1,'local-scope','local-slot','machine',"
            "'node','boot',true,'fixture',%s,'active','endpoint-command','endpoint-operation')",
            (authority.tenant_id, now + timedelta(minutes=10)),
        )
        connection.execute(
            "INSERT INTO operations(operation_id,tenant_id,command_id,provider,provider_workflow_id,status) "
            "VALUES ('delivery-operation',%s,'delivery-command','temporal','delivery-workflow','committed')",
            (authority.tenant_id,),
        )
        connection.execute(
            "INSERT INTO delivery_messages(tenant_id,message_id,command_id,operation_id,endpoint_id,"
            "binding_revision,packet_json,command_json,canonical_hash,envelope_json,envelope_hash,state,"
            "attempts,deadline,maximum_attempts,retry_delay_seconds,policy_hash,accepted_state_digest,"
            "receipt_high_water) VALUES (%s,'message','delivery-command','delivery-operation','endpoint',"
            "1,%s,%s,%s,%s,%s,'delivered',1,%s,3,1,%s,%s,'runtime_dispatched')",
            (authority.tenant_id, json.dumps(packet.model_dump(mode="json")),
             json.dumps({"command_id": "delivery-command"}), "3" * 64,
             json.dumps(envelope.model_dump(mode="json")), digest(envelope.model_dump(mode="json")),
             packet.deadline, "4" * 64, DIGEST),
        )
        connection.execute(
            "INSERT INTO delivery_attempts(tenant_id,message_id,ordinal,attempt_id,operation_id,"
            "endpoint_id,selection_revision,connection_ref,finished_at,deadline,status,selection_json,"
            "selection_digest,invocation_json,invocation_digest,dispatch_id,runtime_dispatched_receipt_id) "
            "VALUES (%s,'message',1,'attempt','delivery-operation','endpoint',1,'connection',"
            "clock_timestamp(),%s,'delivered','{}',%s,%s,%s,%s,%s)",
            (authority.tenant_id, packet.deadline, "5" * 64,
             json.dumps(invocation.model_dump(mode="json")), digest(invocation.model_dump(mode="json")),
             invocation.dispatch_id, invocation.runtime_dispatched_receipt_id),
        )
        connection.execute(
            "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,attempt_id,dispatch_id,"
            "evidence_json) VALUES (%s,'message',%s,'runtime_dispatched','attempt',%s,'{}')",
            (authority.tenant_id, invocation.runtime_dispatched_receipt_id, invocation.dispatch_id),
        )
    return authority, envelope, invocation


def test_projection_surface_applies_once_and_response_consumes_once(recovery_domain):
    authority, _envelope, invocation = recovery_domain
    identity = DispatchIdentity(
        authority.tenant_id, "message", "delivery-operation", invocation.invocation_id,
        "attempt", invocation.dispatch_id, "endpoint", 1, "machine", "node", "boot", 0, DIGEST,
    )
    projection_id = "projection:formal"
    observation = NativeResponseObservation(
        projection_id, response_receipt_id(identity, projection_id), identity,
        "native:response", "completed", "artifact:" + "b" * 64,
        "b" * 64, "c" * 64, datetime.now(UTC),
    )
    raw = {
        "observation": observation.canonical(),
    }
    domain_command = command(
        authority, "delivery.project_native_response", projection_id, raw,
        kind="projection",
    )
    surface = SurfaceCommand.model_validate(domain_command.model_dump(exclude={
        "hash_version", "tenant_id", "authority_id", "authority_incarnation",
        "principal_ref", "grant_ref",
    }))
    result = RecoveryService(authority).execute(surface.to_domain(authority.context),
                                                surface.command_type, raw)
    assert result.state == "applied"
    status = RecoveryService(authority).execute(
        command(authority, "delivery.projection.status", projection_id,
                {"projection_id": projection_id, "scope_id": "local-scope"},
                kind="projection"),
        "delivery.projection.status",
        {"projection_id": projection_id, "scope_id": "local-scope"},
    )
    assert status["disposition"] == "applied"
    consume_payload = {"projection_id": projection_id, "scope_id": "local-scope"}
    consume = command(authority, "delivery.response.consume", projection_id,
                      consume_payload, kind="projection")
    assert RecoveryService(authority).execute(
        consume, "delivery.response.consume", consume_payload,
    ).state == "response_consumed"
    assert RecoveryService(authority).execute(
        consume, "delivery.response.consume", consume_payload,
    ).duplicate
    with pytest.raises(BoundaryRejected, match="already consumed"):
        RecoveryService(authority).execute(
            command(authority, "delivery.response.consume", projection_id,
                    consume_payload, kind="projection", identity="other"),
            "delivery.response.consume", consume_payload,
        )


def _write_manual(root, value):
    inbox = root / "inbox"
    temporary = inbox / ".tmp-manual"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, _canonical(value))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, inbox / "manual.json")


def incident_payload(*, evidence="evidence"):
    return {
        "incident_id": "claim-incident", "generation": 1, "message_id": "message",
        "operation_id": "delivery-operation", "source_scope_id": "local-scope",
        "target_scope_id": "local-scope", "accepted_revision": 0,
        "accepted_state_digest": DIGEST,
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        "eligible_path_ids": ("native",),
        "paths": ({"path_id": "native", "status": "failed",
                   "attempt_refs": ("attempt",), "evidence_refs": (evidence,)},),
    }


def test_persistent_command_claim_serializes_changed_concurrent_input(recovery_domain):
    authority, _envelope, _invocation = recovery_domain
    first_payload = incident_payload(evidence="evidence-a")
    second_payload = incident_payload(evidence="evidence-b")
    first_command = command(
        authority, "recovery.incident.open", "claim-incident", first_payload,
        identity="shared-claim",
    )
    second_command = first_command.model_copy(update={"payload": json.loads(json.dumps(
        second_payload, default=lambda item: item.isoformat(),
    ))})
    barrier = Barrier(2)

    def submit(value, payload):
        barrier.wait(timeout=5)
        try:
            return RecoveryService(authority).execute(
                value, "recovery.incident.open", payload,
            )
        except IdempotencyConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: submit(*item),
            ((first_command, first_payload), (second_command, second_payload)),
        ))
    assert sum(hasattr(result, "state") for result in results) == 1
    assert sum(isinstance(result, IdempotencyConflict) for result in results) == 1
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM recovery_incidents WHERE incident_id='claim-incident'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT state,count(*) FROM recovery_command_claims GROUP BY state"
        ).fetchall() == [("completed", 1)]


def test_persistent_command_claim_serializes_changed_cross_process_input(recovery_domain):
    authority, _envelope, _invocation = recovery_domain
    first_payload = incident_payload(evidence="process-evidence-a")
    second_payload = incident_payload(evidence="process-evidence-b")
    first = command(
        authority, "recovery.incident.open", "claim-incident", first_payload,
        identity="process-claim",
    )
    second = first.model_copy(update={"payload": json.loads(json.dumps(
        second_payload, default=lambda item: item.isoformat(),
    ))})
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    processes = [
        context.Process(
            target=_process_recovery_submit,
            args=(authority._dsn, value.model_dump(mode="json"), payload, start, results),
        )
        for value, payload in ((first, first_payload), (second, second_payload))
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    outcomes = [results.get(timeout=2) for _ in processes]
    assert sorted(outcomes) == [("error", "IdempotencyConflict"), ("result", "open")]
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT state,count(*) FROM recovery_command_claims GROUP BY state"
        ).fetchall() == [("completed", 1)]


@pytest.mark.parametrize("stage", ["after_reserve", "after_action", "after_finalize"])
def test_persistent_command_claim_recovers_each_crash_seam(recovery_domain, stage):
    authority, _envelope, _invocation = recovery_domain
    payload = incident_payload()
    submitted = command(
        authority, "recovery.incident.open", "claim-incident", payload,
        identity="crash-" + stage,
    )
    fired = False

    def fault(observed):
        nonlocal fired
        if observed == stage and not fired:
            fired = True
            raise RuntimeError("injected " + stage)

    with pytest.raises(RuntimeError, match=stage):
        RecoveryService(authority, fault=fault).execute(
            submitted, "recovery.incident.open", payload,
        )
    recovered = RecoveryService(authority).execute(
        submitted, "recovery.incident.open", payload,
    )
    assert recovered.state == "open"
    assert recovered.duplicate is (stage == "after_finalize")
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM recovery_incidents WHERE incident_id='claim-incident'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT state FROM recovery_command_claims WHERE command_id=%s",
            (submitted.command_id,),
        ).fetchone() == ("completed",)
        assert connection.execute(
            "SELECT (result_json->>'state') FROM command_dedup WHERE command_id=%s",
            (submitted.command_id,),
        ).fetchone() == ("open",)


def test_human_request_provider_manual_file_and_normal_confirmation(recovery_domain, tmp_path):
    authority, _envelope, invocation = recovery_domain
    service = RecoveryService(authority)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    open_payload = {
        "incident_id": "incident", "generation": 1, "message_id": "message",
        "operation_id": "delivery-operation", "source_scope_id": "local-scope",
        "target_scope_id": "local-scope", "accepted_revision": 0,
        "accepted_state_digest": DIGEST, "expires_at": expires,
        "eligible_path_ids": ("native",),
        "paths": ({"path_id": "native", "status": "failed",
                   "attempt_refs": ("attempt",), "evidence_refs": ("evidence",)},),
    }
    assert service.execute(
        command(authority, "recovery.incident.open", "incident", open_payload),
        "recovery.incident.open", open_payload,
    ).state == "open"
    request_payload = {"incident_id": "incident", "request_id": "human-request"}
    assert service.execute(
        command(authority, "recovery.human.request", "incident", request_payload),
        "recovery.human.request", request_payload,
    ).state == "human_requested"
    provider_root = tmp_path / "human-provider"
    provision_local_provider(provider_root)
    dispatcher = HumanBridgeProviderDispatcher(authority._dsn, provider_root)
    try:
        published = dispatcher({"tenant_id": authority.tenant_id, "request_id": "human-request"})
        assert published["status"] == "published"
    finally:
        dispatcher.close()
    manual = ManualReturn(
        "acs-human-bridge-manual-return/1", "manual-packet", authority.tenant_id,
        "incident", 1, "message", "delivery-operation", "response", 0, DIGEST,
        "c" * 64, "d" * 64, expires,
    )
    manual.validate()
    _write_manual(provider_root, manual)
    inbox = HumanBridgeManualInbox(authority, provider_root)
    try:
        received = inbox.receive(
            "manual.json", "incident",
            command(authority, "recovery.manual.receive", "incident",
                    {"incident_id": "incident", "packet": {}}, identity="manual"),
        )
        assert received.state == "committed"
    finally:
        inbox.close()
    bridge_evidence = {
        "incident_id": "incident", "incident_generation": 1,
        "packet_id": "manual-packet", "message_id": "message",
        "operation_id": "delivery-operation", "attempt_id": "attempt",
        "dispatch_id": invocation.dispatch_id, "direction": "response",
        "layer": "response_received", "payload_digest": "c" * 64,
    }
    receipt_id = "manual-response-receipt"
    evidence = {"human_bridge": bridge_evidence}
    evidence_digest = canonical_digest({
        "receipt_id": receipt_id, "layer": "response_received", "message_id": "message",
        "evidence": evidence, "attempt_id": "attempt", "dispatch_id": invocation.dispatch_id,
    })
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,attempt_id,"
            "dispatch_id,evidence_json) VALUES (%s,'message',%s,'response_received','attempt',%s,%s)",
            (authority.tenant_id, receipt_id, invocation.dispatch_id, json.dumps(evidence)),
        )
    receipt = {
        **bridge_evidence,
        "tenant_id": authority.tenant_id,
        "receipt_id": receipt_id,
        "evidence_digest": evidence_digest,
    }
    confirm_payload = {"incident_id": "incident", "receipt": receipt}
    assert service.execute(
        command(authority, "recovery.manual.confirm", "incident", confirm_payload,
                identity="confirm"),
        "recovery.manual.confirm", confirm_payload,
    ).state == "resolved_manual"

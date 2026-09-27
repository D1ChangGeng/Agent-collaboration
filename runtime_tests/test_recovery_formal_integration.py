"""Formal schema, Surface, projection and local Human Bridge integration."""
from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from runtime import domain as domain_module
from runtime import recovery_service as recovery_service_module
from runtime.delivery import digest
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import invocation_for
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, IdempotencyConflict
from runtime.harness_sessions import BindingChange
from runtime.human_bridge_dispatch import (
    HumanBridgeManualInbox,
    HumanBridgeProviderDispatcher,
    provision_local_provider,
)
from runtime.human_bridge_file_provider import ManualReturn, _canonical
from runtime.models import CommandEnvelope
from runtime.recovery import (
    DriverCollectorAdapter,
    InvocationCollectionIdentity,
    NodeResponseOutbox,
    ProjectionDisposition,
)
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    HarnessAttemptContext,
    HarnessSessionProof,
    NativeResponseObservation,
    canonical_digest,
    response_receipt_id,
)
from runtime.recovery_service import RecoveryService
from runtime.surfaces import SurfaceCommand
from runtime_tests.test_domain_ledger import isolated_dsn as isolated_dsn  # noqa: PLC0414

DIGEST = "a" * 64


def session_proof():
    return HarnessSessionProof(
        binding_id="harness-fixture", revision=1, driver_kind="opencode",
        native_session_ref="ses-fixture", binding_event_id=1001,
        context=HarnessAttemptContext(
            work_item_id="work", scope_id="local-scope", agent_slot_id="local-slot",
            runtime_id="runtime-fixture", attempt_id="attempt", message_id="message",
            machine_id="machine", node_id="node", node_boot_incarnation="boot",
            node_binding_revision=1, endpoint_id="endpoint", endpoint_binding_revision=1,
        ),
    )


def response_observation(envelope, invocation, proof, projection_id):
    identity = DispatchIdentity(
        envelope.tenant_id, envelope.message_id, envelope.operation_id,
        invocation.invocation_id, invocation.attempt_id, invocation.dispatch_id,
        envelope.endpoint_id, envelope.binding_revision, envelope.machine_id,
        envelope.node_id, envelope.boot_incarnation, invocation.accepted_revision,
        invocation.accepted_state_digest,
    )
    return NativeResponseObservation(
        projection_id, response_receipt_id(identity, projection_id), identity,
        "native:" + projection_id, "completed", "artifact:" + "b" * 64,
        "b" * 64, "c" * 64, datetime.now(UTC), proof,
    )


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


def command(authority, name, target, payload, *, kind="recovery", identity="one", revision=0):
    now = datetime.now(UTC)
    payload = json.loads(json.dumps(payload, default=lambda item: item.isoformat()))
    return CommandEnvelope(
        command_id=f"{name}:{identity}", idempotency_key=f"key:{name}:{identity}",
        correlation_id="recovery-integration", command_type=name,
        tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref,
        target_kind=kind, target_id=target, expected_revision=revision,
        issued_at=now, deadline=now + timedelta(minutes=5), payload=payload,
    )


@pytest.fixture
def recovery_domain(isolated_dsn, tmp_path):
    response_outbox = NodeResponseOutbox(tmp_path / "node-response.sqlite")
    authority = DomainAuthority(isolated_dsn, node_response_reader=response_outbox.by_invocation)
    authority._test_response_outbox = response_outbox
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "delivery.project", "delivery.read", "delivery.consume",
        "recovery.manage", "recovery.read", "human_bridge.send", "human_bridge.receive",
        "harness_session.manage", "harness_session.read",
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
    selected = {
        "scope_id": "local-scope", "agent_slot_id": "local-slot", "machine_id": "machine",
        "node_id": "node", "boot_incarnation": "boot", "endpoint_id": "endpoint", "revision": 1,
    }
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
            "INSERT INTO enrolled_runtimes(tenant_id,runtime_id,node_id,node_binding_revision,"
            "node_boot_incarnation,scope_id,agent_slot_id,producer_ref,producer_grant_ref,"
            "observer_ref,observer_grant_ref,authority_id,authority_incarnation,provider,"
            "status,expires_at,command_id,operation_id) VALUES "
            "(%s,'runtime-fixture','node',1,'boot','local-scope','local-slot','producer',"
            "%s,'observer',%s,%s,%s,'fixture','active',%s,'runtime-command','runtime-operation')",
            (authority.tenant_id, authority.context.grant_ref, authority.context.grant_ref,
             authority.context.authority_id, authority.context.authority_incarnation,
             now + timedelta(minutes=10)),
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
             packet.deadline, digest({}), DIGEST),
        )
        connection.execute(
            "INSERT INTO delivery_attempts(tenant_id,message_id,ordinal,attempt_id,operation_id,"
            "endpoint_id,selection_revision,connection_ref,finished_at,deadline,status,selection_json,"
            "selection_digest,invocation_json,invocation_digest,dispatch_id,runtime_dispatched_receipt_id) "
            "VALUES (%s,'message',1,'attempt','delivery-operation','endpoint',1,'connection',"
            "clock_timestamp(),%s,'delivered',%s,%s,%s,%s,%s,%s)",
            (authority.tenant_id, packet.deadline, json.dumps(selected), digest(selected),
             json.dumps(invocation.model_dump(mode="json")), digest(invocation.model_dump(mode="json")),
             invocation.dispatch_id, invocation.runtime_dispatched_receipt_id),
        )
        connection.execute(
            "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,attempt_id,dispatch_id,"
            "evidence_json) VALUES (%s,'message',%s,'runtime_dispatched','attempt',%s,'{}')",
            (authority.tenant_id, invocation.runtime_dispatched_receipt_id, invocation.dispatch_id),
        )
        proof = session_proof()
        connection.execute(
            "INSERT INTO domain_events(event_id,tenant_id,work_item_id,target_kind,target_id,"
            "related_work_item_id,to_state,initiated_by,lineage_mode,command_id,resulting_revision,"
            "evidence_refs,command_hash_version,canonical_hash) VALUES "
            "(1001,%s,NULL,'harness_session','work','work','active','fixture-agent',"
            "'external_command','fixture-command',1,'[]','v2',%s)",
            (authority.tenant_id, "f" * 64),
        )
        connection.execute(
            "INSERT INTO harness_session_heads(tenant_id,work_item_id,scope_id,agent_slot_id,"
            "revision,active_binding_id) VALUES (%s,'work','local-scope','local-slot',1,%s)",
            (authority.tenant_id, proof.binding_id),
        )
        connection.execute(
            "INSERT INTO harness_session_bindings(tenant_id,binding_id,work_item_id,scope_id,"
            "agent_slot_id,revision,driver_kind,native_session_ref,installed_version,receipt_ref,"
            "attempt_context,attached_event_id,status,attached_by,attached_command_id) VALUES "
            "(%s,%s,'work','local-scope','local-slot',1,'opencode','ses-fixture','1.18.30',"
            "'receipt:fixture',%s,%s,'active','fixture-agent','fixture-command')",
            (authority.tenant_id, proof.binding_id, json.dumps(asdict(proof.context)),
             proof.binding_event_id),
        )
    return authority, envelope, invocation


def test_projection_surface_applies_once_and_response_consumes_once(recovery_domain):
    authority, envelope, invocation = recovery_domain
    projection_id = "projection:formal"
    observation = response_observation(envelope, invocation, session_proof(), projection_id)
    authority._test_response_outbox.record(observation)
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


def test_other_scope_grant_cannot_read_or_consume_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:scope-readback")
    authority._test_response_outbox.record(item)
    projected = {"observation": item.canonical()}
    assert RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                projected, kind="projection", identity="scope-project"),
        "delivery.project_native_response", projected,
    ).state == "applied"
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO scopes(scope_id,tenant_id,policy,status) "
            "VALUES ('other-scope',%s,'{}','active')",
            (authority.tenant_id,),
        )
        connection.execute(
            "INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,"
            "authority_incarnation,scope_id,permissions,expires_at) "
            "VALUES ('grant:other',%s,%s,%s,%s,'other-scope',%s,clock_timestamp()+interval '5 minutes')",
            (authority.tenant_id, authority.context.principal_ref,
             authority.context.authority_id, authority.context.authority_incarnation,
             json.dumps(["delivery.read", "delivery.consume"])),
        )
    other = DomainAuthority(
        authority._dsn, context=replace(authority.context, grant_ref="grant:other"),
    )
    target = {"projection_id": item.projection_id, "scope_id": "other-scope"}
    assert RecoveryService(other).execute(
        command(other, "delivery.projection.status", item.projection_id,
                target, kind="projection", identity="other-read"),
        "delivery.projection.status", target,
    ) is None
    with pytest.raises(BoundaryRejected, match="applied native response is unavailable"):
        RecoveryService(other).execute(
            command(other, "delivery.response.consume", item.projection_id,
                    target, kind="projection", identity="other-consume"),
            "delivery.response.consume", target,
        )
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_consumptions").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM recovery_command_claims WHERE command_id=%s",
            ("delivery.response.consume:other-consume",),
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_native_projection_requires_versioned_harness_proof(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, None, "projection:no-proof")
    authority._test_response_outbox.record(item)
    payload = {"observation": item.canonical()}
    with pytest.raises(BoundaryRejected, match="Harness session proof"):
        RecoveryService(authority).execute(
            command(authority, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="no-proof"),
            "delivery.project_native_response", payload,
        )
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM native_response_observations"
        ).fetchone() == (0,)


def test_node_outbox_readback_rejects_changed_projection_body(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:changed-body")
    authority._test_response_outbox.record(item)
    changed = item.canonical()
    changed["evidence_digest"] = "d" * 64
    payload = {"observation": changed}
    with pytest.raises(BoundaryRejected, match="Node response Outbox differs"):
        RecoveryService(authority).execute(
            command(authority, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="changed-body"),
            "delivery.project_native_response", payload,
        )
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM recovery_command_claims").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)


def test_projection_without_trusted_node_reader_fails_closed(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:no-reader")
    authority._test_response_outbox.record(item)
    payload = {"observation": item.canonical()}
    unconfigured = DomainAuthority(authority._dsn, context=authority.context)
    with pytest.raises(BoundaryRejected, match="trusted Node response readback"):
        RecoveryService(unconfigured).execute(
            command(unconfigured, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="no-reader"),
            "delivery.project_native_response", payload,
        )
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM recovery_command_claims").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)


def _replacement_attempt(authority, envelope):
    now = datetime.now(UTC)
    proof = session_proof()
    new_context = replace(proof.context, runtime_id="runtime-fixture-2", attempt_id="attempt-2")
    new_proof = replace(proof, binding_id="harness-fixture-2", revision=2,
                        native_session_ref="ses-fixture-2", context=new_context)
    invocation = invocation_for(envelope, new_context.attempt_id)
    selected = {
        "scope_id": "local-scope", "agent_slot_id": "local-slot", "machine_id": "machine",
        "node_id": "node", "boot_incarnation": "boot", "endpoint_id": "endpoint", "revision": 1,
    }
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO enrolled_runtimes(tenant_id,runtime_id,node_id,node_binding_revision,"
            "node_boot_incarnation,scope_id,agent_slot_id,producer_ref,producer_grant_ref,"
            "observer_ref,observer_grant_ref,authority_id,authority_incarnation,provider,"
            "status,expires_at,command_id,operation_id) VALUES "
            "(%s,'runtime-fixture-2','node',1,'boot','local-scope','local-slot','producer-2',"
            "%s,'observer',%s,%s,%s,'fixture','active',%s,'runtime-command-2','runtime-operation-2')",
            (authority.tenant_id, authority.context.grant_ref, authority.context.grant_ref,
             authority.context.authority_id, authority.context.authority_incarnation,
             now + timedelta(minutes=10)),
        )
        connection.execute(
            "INSERT INTO delivery_attempts(tenant_id,message_id,ordinal,attempt_id,operation_id,"
            "endpoint_id,selection_revision,connection_ref,finished_at,deadline,status,selection_json,"
            "selection_digest,invocation_json,invocation_digest,dispatch_id,runtime_dispatched_receipt_id) "
            "VALUES (%s,'message',2,'attempt-2','delivery-operation','endpoint',1,'connection-2',"
            "clock_timestamp(),%s,'delivered',%s,%s,%s,%s,%s,%s)",
            (authority.tenant_id, envelope.packet.deadline, json.dumps(selected), digest(selected),
             json.dumps(invocation.model_dump(mode="json")), digest(invocation.model_dump(mode="json")),
             invocation.dispatch_id, invocation.runtime_dispatched_receipt_id),
        )
        connection.execute(
            "UPDATE delivery_messages SET attempts=2 WHERE tenant_id=%s AND message_id='message'",
            (authority.tenant_id,),
        )
        connection.execute(
            "UPDATE delivery_receipts SET receipt_id=%s,attempt_id='attempt-2',dispatch_id=%s "
            "WHERE tenant_id=%s AND message_id='message' AND layer='runtime_dispatched'",
            (invocation.runtime_dispatched_receipt_id, invocation.dispatch_id, authority.tenant_id),
        )
    request = BindingChange(
        binding_id=new_proof.binding_id, scope_id="local-scope", agent_slot_id="local-slot",
        driver_kind="opencode", native_session_ref=new_proof.native_session_ref,
        installed_version="1.18.30", receipt_ref="receipt:replacement",
        attempt_context=new_context,
    )
    result = authority.harness_sessions.change(
        command(authority, "harness_session.replace", "work", request.model_dump(mode="json"),
                kind="work_item", identity="replacement", revision=1), request,
    )
    assert result.revision == 2
    with authority._connect() as connection:
        event_id = connection.execute(
            "SELECT attached_event_id FROM harness_session_bindings "
            "WHERE tenant_id=%s AND binding_id=%s",
            (authority.tenant_id, new_proof.binding_id),
        ).fetchone()[0]
    assert isinstance(event_id, int) and event_id > 0
    return invocation, replace(new_proof, binding_event_id=event_id)


def _fixture_terminal(outbox, envelope, invocation, proof, turn):
    identity = response_observation(envelope, invocation, proof, "unused").identity
    binding = {
        "node_id": proof.context.node_id,
        "node_boot_id": proof.context.node_boot_incarnation,
        "runtime_id": proof.context.runtime_id,
        "attempt_id": proof.context.attempt_id,
        "agent_slot_id": proof.context.agent_slot_id,
        "revision": proof.context.node_binding_revision,
    }
    collection = InvocationCollectionIdentity(
        dispatch=identity, command_id=envelope.command_id,
        binding_id="driver:" + proof.binding_id,
        binding_items=tuple(binding.items()), driver_kind="opencode",
        native_session_ref=proof.native_session_ref, native_turn_ref=turn,
        harness_proof=proof,
    )

    class FixtureDriver:
        calls = 0

        def collect_result(self, _operation, _operation_id):
            self.calls += 1
            return {
                "receipt_layer": "response_received", "operation_id": identity.operation_id,
                "command_id": envelope.command_id, "message_id": identity.message_id,
                "invocation_id": identity.invocation_id, "attempt_id": identity.attempt_id,
                "dispatch_id": identity.dispatch_id, "binding_id": collection.binding_id,
                "binding": binding, "native_session_id": proof.native_session_ref,
                "native_message_id": turn, "native_terminal_outcome": "completed",
                "native_terminal_observed_at": datetime.now(UTC).isoformat(),
            }

        def invoke(self, *_args, **_kwargs):
            raise AssertionError("fixture collector must not invoke a model")

    driver = FixtureDriver()
    observation = DriverCollectorAdapter(
        driver, outbox,
        lambda value: ("artifact:" + canonical_digest(value), canonical_digest(value)),
    ).collect(object(), identity.operation_id, collection)
    assert driver.calls == 1
    return observation


def test_replacement_fences_old_node_result_and_promotes_current_only(recovery_domain):
    authority, envelope, old_invocation = recovery_domain
    original = session_proof()
    work_before = None
    with authority._connect() as connection:
        work_before = connection.execute(
            "SELECT scope_id,agent_slot_id,revision,state FROM work_items WHERE work_item_id='work'"
        ).fetchone()
    outbox = authority._test_response_outbox
    old = _fixture_terminal(outbox, envelope, old_invocation, original, "old-turn")
    assert outbox.by_invocation(old.identity).harness_proof == original
    new_invocation, replacement = _replacement_attempt(authority, envelope)
    history = authority.harness_sessions.read(
        command(authority, "harness_session.read", "work", {}, kind="work_item", revision=2)
    )
    assert (history["scope_id"], history["agent_slot_id"], history["active_binding_id"]) == (
        "local-scope", "local-slot", replacement.binding_id)
    assert [(row["binding_id"], row["status"]) for row in history["bindings"]] == [
        (original.binding_id, "retired"), (replacement.binding_id, "active")]
    old_payload = {"observation": old.canonical()}
    late = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", old.projection_id,
                old_payload, kind="projection", identity="old-late"),
        "delivery.project_native_response", old_payload,
    )
    assert late.state == "fenced_late"
    outbox.mark(ProjectionDisposition(old.projection_id, NodeResponseOutbox._payload(old)[1], late.state))
    late_target = {"projection_id": old.projection_id, "scope_id": "local-scope"}
    late_status = RecoveryService(authority).execute(
        command(authority, "delivery.projection.status", old.projection_id,
                late_target, kind="projection", identity="old-status"),
        "delivery.projection.status", late_target,
    )
    assert late_status["disposition"] == "fenced_late"
    assert late_status["harness_proof"]["binding_id"] == original.binding_id
    with pytest.raises(BoundaryRejected, match="applied native response is unavailable"):
        RecoveryService(authority).execute(
            command(authority, "delivery.response.consume", old.projection_id,
                    late_target, kind="projection", identity="old-consume"),
            "delivery.response.consume", late_target,
        )
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM native_response_consumptions").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM recovery_command_claims WHERE command_id=%s",
            ("delivery.response.consume:old-consume",),
        ).fetchone() == (0,)
    current = _fixture_terminal(outbox, envelope, new_invocation, replacement, "new-turn")
    current_payload = {"observation": current.canonical()}
    applied = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", current.projection_id,
                current_payload, kind="projection", identity="new-current"),
        "delivery.project_native_response", current_payload,
    )
    assert applied.state == "applied"
    outbox.mark(ProjectionDisposition(current.projection_id,
                                      NodeResponseOutbox._payload(current)[1], applied.state))
    assert outbox.recover() == ()
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT disposition,harness_proof->>'binding_id' "
            "FROM native_response_observations ORDER BY disposition DESC"
        ).fetchall() == [("fenced_late", original.binding_id), ("applied", replacement.binding_id)]
        assert connection.execute(
            "SELECT attempt_id FROM delivery_receipts WHERE layer='response_received'"
        ).fetchall() == [(new_invocation.attempt_id,)]
        assert connection.execute(
            "SELECT scope_id,agent_slot_id,revision,state FROM work_items WHERE work_item_id='work'"
        ).fetchone() == work_before
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_revoked_projection_grant_cannot_promote_native_response(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:revoked")
    authority._test_response_outbox.record(item)
    read_calls = []
    original_reader = authority._node_response_reader

    def counted_reader(identity):
        read_calls.append(identity)
        return original_reader(identity)

    authority._node_response_reader = counted_reader
    with authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (authority.context.grant_ref,))
    payload = {"observation": item.canonical()}
    with pytest.raises(AuthorizationDenied):
        RecoveryService(authority).execute(
            command(authority, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="revoked"),
            "delivery.project_native_response", payload,
        )
    assert read_calls == []
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)


def test_grant_revoked_after_reservation_blocks_final_node_readback(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:revoke-after-reserve")
    authority._test_response_outbox.record(item)
    read_calls = []
    original_reader = authority._node_response_reader

    def counted_reader(identity):
        read_calls.append(identity)
        return original_reader(identity)

    def revoke(stage):
        if stage == "after_reserve":
            with authority._connect() as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                                   (authority.context.grant_ref,))

    authority._node_response_reader = counted_reader
    payload = {"observation": item.canonical()}
    with pytest.raises(AuthorizationDenied):
        RecoveryService(authority, fault=revoke).execute(
            command(authority, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="revoke-after-reserve"),
            "delivery.project_native_response", payload,
        )
    assert len(read_calls) == 1  # The final protected boundary did not read Node again.
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)


def test_revoked_agent_slot_fences_current_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:slot-revoked")
    authority._test_response_outbox.record(item)
    with authority._connect() as connection:
        connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'")
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="slot-revoked"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    assert authority.harness_sessions.read(
        command(authority, "harness_session.read", "work", {}, kind="work_item", revision=1)
    )["active_binding_id"] == session_proof().binding_id
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


@pytest.mark.parametrize("expired", ["node", "runtime"])
def test_database_clock_fences_expired_binding_despite_client_clock_skew(
    recovery_domain, monkeypatch, expired,
):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(),
                                "projection:expired-" + expired)
    authority._test_response_outbox.record(item)
    with authority._connect() as connection:
        if expired == "node":
            connection.execute(
                "UPDATE enrolled_node_bindings SET expires_at=clock_timestamp()-interval '10 seconds' "
                "WHERE node_id='node' AND binding_revision=1"
            )
            expired_at = connection.execute(
                "SELECT expires_at FROM enrolled_node_bindings WHERE node_id='node' "
                "AND binding_revision=1"
            ).fetchone()[0]
        else:
            connection.execute(
                "UPDATE enrolled_runtimes SET expires_at=clock_timestamp()-interval '10 seconds' "
                "WHERE runtime_id='runtime-fixture'"
            )
            expired_at = connection.execute(
                "SELECT expires_at FROM enrolled_runtimes WHERE runtime_id='runtime-fixture'"
            ).fetchone()[0]
        assert connection.execute("SELECT clock_timestamp() > %s", (expired_at,)).fetchone() == (True,)
        work_before = connection.execute(
            "SELECT revision,state,source_baseline FROM work_items WHERE work_item_id='work'"
        ).fetchone()

    class BehindClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(hours=1)

    monkeypatch.setattr(recovery_service_module, "datetime", BehindClock)
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="expired-" + expired),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT disposition FROM native_response_observations WHERE projection_id=%s",
            (item.projection_id,),
        ).fetchone() == ("fenced_late",)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT revision,state,source_baseline FROM work_items WHERE work_item_id='work'"
        ).fetchone() == work_before
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


@pytest.mark.parametrize("expired", ["grant", "deadline"])
def test_database_clock_rejects_expired_authorization_before_node_readback(
    recovery_domain, monkeypatch, expired,
):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(),
                                "projection:expired-" + expired)
    authority._test_response_outbox.record(item)
    read_calls = []
    original_reader = authority._node_response_reader

    def counted_reader(identity):
        read_calls.append(identity)
        return original_reader(identity)

    authority._node_response_reader = counted_reader
    if expired == "grant":
        with authority._connect() as connection:
            connection.execute(
                "UPDATE grants SET expires_at=clock_timestamp()-interval '10 seconds' "
                "WHERE grant_ref=%s", (authority.context.grant_ref,),
            )
            assert connection.execute(
                "SELECT expires_at<clock_timestamp() FROM grants WHERE grant_ref=%s",
                (authority.context.grant_ref,),
            ).fetchone() == (True,)

    class BehindClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(hours=1)

    monkeypatch.setattr(domain_module, "datetime", BehindClock)
    monkeypatch.setattr(recovery_service_module, "datetime", BehindClock)
    payload = {"observation": item.canonical()}
    submitted = command(
        authority, "delivery.project_native_response", item.projection_id,
        payload, kind="projection", identity="expired-" + expired,
    ).model_copy(update={
        "issued_at": datetime.now(UTC) - timedelta(hours=2),
        "deadline": datetime.now(UTC) - timedelta(seconds=10)
        if expired == "deadline" else datetime.now(UTC) + timedelta(minutes=5),
    })
    if expired == "deadline":
        with authority._connect() as connection:
            assert connection.execute("SELECT clock_timestamp()>%s", (submitted.deadline,)).fetchone() == (True,)
    with pytest.raises(AuthorizationDenied):
        RecoveryService(authority).execute(
            submitted,
            "delivery.project_native_response", payload,
        )
    assert read_calls == []
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM recovery_command_claims").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_changed_scope_policy_fences_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:policy-change")
    authority._test_response_outbox.record(item)
    with authority._connect() as connection:
        connection.execute(
            "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
            (json.dumps({"version": 2, "native_response": "deny"}),),
        )
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="policy-change"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_changed_work_item_baseline_fences_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:new-baseline")
    authority._test_response_outbox.record(item)
    with authority._connect() as connection:
        connection.execute("UPDATE work_items SET source_baseline='replacement-baseline' "
                           "WHERE work_item_id='work'")
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="new-baseline"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT source_baseline FROM work_items WHERE work_item_id='work'").fetchone() == (
            "replacement-baseline",)


def test_new_accepted_state_revision_fences_old_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(envelope, invocation, session_proof(), "projection:new-accepted")
    authority._test_response_outbox.record(item)
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO accepted_state_revisions(tenant_id,work_item_id,revision,baseline_ref,"
            "evidence_refs,review_ref,effect_refs,readback_refs) "
            "VALUES (%s,'work',1,'new-baseline','[]','new-review','[]','[]')",
            (authority.tenant_id,),
        )
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="new-accepted"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT revision,baseline_ref FROM accepted_state_revisions WHERE work_item_id='work'"
        ).fetchall() == [(1, "new-baseline")]


def test_missing_committed_binding_event_fences_native_projection(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = response_observation(
        envelope, invocation, replace(session_proof(), binding_event_id=None),
        "projection:no-binding-event",
    )
    authority._test_response_outbox.record(item)
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="no-binding-event"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "fenced_late"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)


def test_wrong_binding_event_is_rejected_before_response_receipt(recovery_domain):
    authority, envelope, invocation = recovery_domain
    forged = replace(session_proof(), binding_event_id=9999)
    item = response_observation(envelope, invocation, forged, "projection:wrong-event")
    authority._test_response_outbox.record(item)
    payload = {"observation": item.canonical()}
    with pytest.raises(BoundaryRejected, match="binding event proof changed"):
        RecoveryService(authority).execute(
            command(authority, "delivery.project_native_response", item.projection_id,
                    payload, kind="projection", identity="wrong-event"),
            "delivery.project_native_response", payload,
        )
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)


def test_cross_machine_observation_clock_does_not_replace_causal_event(recovery_domain):
    authority, envelope, invocation = recovery_domain
    item = replace(
        response_observation(envelope, invocation, session_proof(), "projection:clock-skew"),
        observed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    authority._test_response_outbox.record(item)
    payload = {"observation": item.canonical()}
    result = RecoveryService(authority).execute(
        command(authority, "delivery.project_native_response", item.projection_id,
                payload, kind="projection", identity="clock-skew"),
        "delivery.project_native_response", payload,
    )
    assert result.state == "applied"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (1,)


def test_concurrent_old_session_projections_share_one_fenced_observation(recovery_domain):
    authority, envelope, invocation = recovery_domain
    _replacement_attempt(authority, envelope)
    old = response_observation(envelope, invocation, session_proof(), "projection:concurrent-old")
    authority._test_response_outbox.record(old)
    payload = {"observation": old.canonical()}
    barrier = Barrier(2)

    def submit(identity):
        barrier.wait(timeout=10)
        return RecoveryService(authority).execute(
            command(authority, "delivery.project_native_response", old.projection_id,
                    payload, kind="projection", identity=identity),
            "delivery.project_native_response", payload,
        ).state

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, label) for label in ("late-a", "late-b")]
        assert [future.result(timeout=15) for future in futures] == ["fenced_late", "fenced_late"]
    with authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM native_response_observations").fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


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


def test_human_confirmation_reuses_existing_native_response_receipt(recovery_domain, tmp_path):
    authority, _envelope, invocation = recovery_domain
    service = RecoveryService(authority)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    open_payload = {
        "incident_id": "native-incident", "generation": 1, "message_id": "message",
        "operation_id": "delivery-operation", "source_scope_id": "local-scope",
        "target_scope_id": "local-scope", "accepted_revision": 0,
        "accepted_state_digest": DIGEST, "expires_at": expires,
        "eligible_path_ids": ("native",),
        "paths": ({"path_id": "native", "status": "failed",
                   "attempt_refs": ("attempt",), "evidence_refs": ("native-fault",)},),
    }
    assert service.execute(
        command(authority, "recovery.incident.open", "native-incident", open_payload),
        "recovery.incident.open", open_payload,
    ).state == "open"
    request_payload = {"incident_id": "native-incident", "request_id": "native-human-request"}
    assert service.execute(
        command(authority, "recovery.human.request", "native-incident", request_payload),
        "recovery.human.request", request_payload,
    ).state == "human_requested"
    provider_root = tmp_path / "native-human-provider"
    provision_local_provider(provider_root)
    dispatcher = HumanBridgeProviderDispatcher(authority._dsn, provider_root)
    try:
        assert dispatcher({"tenant_id": authority.tenant_id, "request_id": "native-human-request"})["status"] == "published"
    finally:
        dispatcher.close()
    manual = ManualReturn(
        "acs-human-bridge-manual-return/1", "native-manual-packet", authority.tenant_id,
        "native-incident", 1, "message", "delivery-operation", "response", 0,
        DIGEST, "c" * 64, "d" * 64, expires,
    )
    manual.validate()
    _write_manual(provider_root, manual)
    inbox = HumanBridgeManualInbox(authority, provider_root)
    try:
        received = inbox.receive(
            "manual.json", "native-incident",
            command(authority, "recovery.manual.receive", "native-incident",
                    {"incident_id": "native-incident", "packet": {}}, identity="native-manual"),
        )
        assert received.state == "committed"
    finally:
        inbox.close()
    native_evidence = {"native": {"response_ref": "native-response", "outcome": "completed"}}
    receipt_id = "native-response-receipt"
    evidence_digest = canonical_digest({
        "receipt_id": receipt_id, "layer": "response_received", "message_id": "message",
        "evidence": native_evidence, "attempt_id": "attempt", "dispatch_id": invocation.dispatch_id,
    })
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,attempt_id,"
            "dispatch_id,evidence_json) VALUES (%s,'message',%s,'response_received','attempt',%s,%s)",
            (authority.tenant_id, receipt_id, invocation.dispatch_id, json.dumps(native_evidence)),
        )
    receipt = {
        "incident_id": "native-incident", "incident_generation": 1,
        "packet_id": "native-manual-packet", "tenant_id": authority.tenant_id,
        "message_id": "message", "operation_id": "delivery-operation",
        "attempt_id": "attempt", "dispatch_id": invocation.dispatch_id,
        "direction": "response", "layer": "response_received", "payload_digest": "c" * 64,
        "receipt_id": receipt_id, "evidence_digest": evidence_digest,
    }
    assert service.execute(
        command(authority, "recovery.manual.confirm", "native-incident",
                {"incident_id": "native-incident", "receipt": receipt}, identity="native-confirm"),
        "recovery.manual.confirm", {"incident_id": "native-incident", "receipt": receipt},
    ).state == "resolved_manual"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE tenant_id=%s AND message_id='message' AND layer='response_received'",
            (authority.tenant_id,),
        ).fetchone() == (1,)

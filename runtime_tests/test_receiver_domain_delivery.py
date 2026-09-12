"""Real PostgreSQL plus separate TLS receiver integration."""
from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import socket
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from nacl.signing import SigningKey
from psycopg import sql
from psycopg.conninfo import make_conninfo
from temporalio.client import Client

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_temporal import delivery_worker, submit_delivery
from runtime.domain import DomainAuthority
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    RuntimeRegistration,
)
from runtime.models import CommandEnvelope
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import public_key, sign
from runtime.receiver_delivery import ReceiverDeployment, RemoteNodeEndpointAdapter
from runtime.receiver_deployment import (
    bind_process_config,
    dump_process_config,
)
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.remote_endpoint import RemoteNodeTransport, serve
from runtime.surfaces import SharedService, SurfaceCommand
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_tests.receiver_deployment_fixture import configured_factory_binding
from runtime_tests.test_receiver_protocol import certificate


def command(domain, kind, target_kind, target_id, revision=0):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return CommandEnvelope(
        command_id=f"receiver-command-{identity}", idempotency_key=f"receiver-key-{identity}",
        command_type=kind, correlation_id="receiver-integration", tenant_id=domain.tenant_id,
        authority_id=domain.context.authority_id,
        authority_incarnation=domain.context.authority_incarnation,
        principal_ref=domain.context.principal_ref, grant_ref=domain.context.grant_ref,
        target_kind=target_kind, target_id=target_id, expected_revision=revision,
        issued_at=now, deadline=now + timedelta(minutes=3),
    )


def proof(node_domain, node_key, node_id, purpose_command, node_input, revision=1):
    challenge = node_domain.challenge_node(
        command(node_domain, "node.challenge", "node", node_id, revision),
        NodeChallengeRequest(
            purpose=purpose_command.command_type,
            purpose_command_id=purpose_command.command_id,
            purpose_hash=EnrollmentAuthority.signing_hash(purpose_command, node_input),
            ttl_seconds=120,
        ),
    )
    return NodeCommandProof(
        challenge_id=challenge.challenge_id,
        signature=node_key.sign(bytes.fromhex(challenge.message_hex)).signature.hex(),
    )


def free_port():
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


def native_no_model(admission):
    return {"native_ack_ref": f"no-model:{admission.dispatch_id}", "model_invoked": False}


@pytest.fixture
def integrated(tmp_path):
    base = os.getenv("ACS_P1_DSN")
    if not base or os.name != "posix":
        pytest.skip("real Linux PostgreSQL receiver integration required")
    schema = "receiver_domain_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema} -c lock_timeout=5000")
    process = None
    supervisor = None
    handle = None
    try:
        authority = DomainAuthority(dsn)
        authority.initialize()
        authority.bootstrap_local_grant((
            "work_item.create", "work_item.read", "enrollment.manage", "receiver.manage",
            "delivery.manage", "message.send", "message.read", "runtime.invoke",
        ))
        node = DomainAuthority(
            dsn,
            context=replace(
                authority.context, principal_ref="receiver-node",
                grant_ref="grant:receiver-node",
            ),
        )
        node.bootstrap_local_grant((
            "runtime.register", "attempt.register", "execution.record", "endpoint.register",
            "delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover",
            "work_item.read",
        ))
        node_key = SigningKey.generate()
        node_id = "receiver-node"
        authority.enroll_node(
            command(authority, "node.enroll", "node", node_id),
            NodeEnrollment(
                scope_id="local-scope", agent_slot_id="local-slot",
                observer_grant_ref=node.context.grant_ref, machine_id="receiver-machine",
                boot_incarnation="receiver-boot-1", public_key=public_key(node_key),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )
        runtime_request = RuntimeRegistration(
            node_id=node_id, node_binding_revision=1, provider="receiver-tls",
            producer_grant_ref=authority.context.grant_ref,
            expires_at=datetime.now(UTC) + timedelta(minutes=4),
        )
        runtime_command = command(node, "runtime.register", "runtime", "receiver-runtime")
        node.register_runtime(
            runtime_command, runtime_request,
            proof(node, node_key, node_id, runtime_command,
                  {"request": runtime_request.model_dump(mode="json")}),
        )
        authority_key = SigningKey.generate()
        authority_seed = tmp_path / "authority.seed"
        authority_seed.write_text(authority_key.encode().hex(), encoding="ascii")
        authority_seed.chmod(0o600)
        authority.register_authority_transport_key(
            command(authority, "receiver.key.register", "authority_transport_key", "authority-key-1"),
            AuthorityTransportKeyRegistration(
                key_id="authority-key-1", revision=1, public_key=public_key(authority_key),
                expires_at=datetime.now(UTC) + timedelta(minutes=4),
            ),
        )
        port = free_port()
        authority.register_receiver_connection(
            command(authority, "receiver.connection.register", "connection", "receiver-loopback"),
            ConnectionReferenceRegistration(
                connection_ref="receiver-loopback", revision=1, locator_host="127.0.0.1",
                locator_port=port, route_class="loopback", policy_digest="c" * 64,
                expires_at=datetime.now(UTC) + timedelta(minutes=4),
            ),
        )
        cert_path, tls_key_path, cert_hash = certificate(tmp_path)
        node_seed = tmp_path / "node.seed"
        node_seed.write_text(node_key.encode().hex(), encoding="ascii")
        node_seed.chmod(0o600)
        provisional_registration = EndpointRegistration(
            registration_id="receiver-registration-1", endpoint_id="receiver-endpoint",
            endpoint_revision=1, connection_ref="receiver-loopback", tenant_id=authority.tenant_id,
            authority_id=authority.context.authority_id,
            authority_incarnation=authority.context.authority_incarnation,
            node_id=node_id, node_binding_revision=1, runtime_id="receiver-runtime",
            runtime_revision=1, machine_id="receiver-machine", boot_incarnation="receiver-boot-1",
            scope_id="local-scope", agent_slot_id="local-slot",
            tls_certificate_sha256=cert_hash, config_sha256="0" * 64,
            expires_at=datetime.now(UTC) + timedelta(seconds=90),
        )
        with authority._connect() as connection:
            node_key_id = connection.execute(
                "SELECT key_id FROM enrolled_node_bindings WHERE tenant_id=%s AND node_id=%s "
                "AND binding_revision=1",
                (authority.tenant_id, node_id),
            ).fetchone()[0]
        provisional_binding = EndpointBinding(
            registration=provisional_registration, locator_host="127.0.0.1", locator_port=port,
            route_class="loopback", node_key_id=node_key_id, node_public_key=public_key(node_key),
            registration_signature=sign(node_key, provisional_registration),
        )
        provisional_config = ReceiverRuntimeConfig(
            binding=provisional_binding, authority_key_id="authority-key-1",
            authority_key_revision=1, authority_public_key=public_key(authority_key),
            authority_public_key_fingerprint=hashlib.sha256(
                bytes.fromhex(public_key(authority_key))
            ).hexdigest(),
            tls_cert_path=str(cert_path), tls_key_path=str(tls_key_path),
            node_signing_key_path=str(node_seed), ledger_path=str(tmp_path / "receiver.sqlite"),
            expected_boot_incarnation="receiver-boot-1", journal_generation=1,
        )
        factory, _, _, _ = configured_factory_binding()
        process_config = bind_process_config(provisional_config, factory, node_key)
        registration = process_config.runtime.binding.registration
        endpoint_command = command(node, "endpoint.register", "endpoint", "receiver-endpoint")
        registration_signature = process_config.runtime.binding.registration_signature
        node_input = {
            "registration": registration.model_dump(mode="json"),
            "registration_signature": registration_signature,
        }
        node.register_receiver_endpoint(
            endpoint_command,
            EndpointRegistrationCommand(
                registration=registration, registration_signature=registration_signature,
                proof=proof(node, node_key, node_id, endpoint_command, node_input),
            ),
        )
        deployment = ReceiverDeployment(
            authority_signing_key_path=str(authority_seed), tls_cert_path=str(cert_path),
            tls_key_path=str(tls_key_path), node_signing_key_path=str(node_seed),
            ledger_path=str(tmp_path / "receiver.sqlite"),
            expected_boot_incarnation="receiver-boot-1", journal_generation=1,
        )
        adapter = RemoteNodeEndpointAdapter(authority, "receiver-endpoint", deployment)
        assert adapter.config == process_config.runtime
        config_path = tmp_path / "receiver-process.json"
        config_path.write_text(dump_process_config(process_config), encoding="utf-8")
        config_path.chmod(0o600)
        installed = os.getenv("ACS_INSTALLED_RECEIVER")
        if installed:
            supervisor = SystemdUserSupervisor(
                tasks_max=32, memory_max=268_435_456, cpu_quota_percent=50,
                termination_timeout=10,
            )
            service_env = {
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "ACS_RECEIVER_DSN": dsn,
                "ACS_RECEIVER_P1_MODE": "no-model-validation",
                "PYTHONNOUSERSITE": "1",
            }
            handle = supervisor.launch(
                [installed, "--config", str(config_path)], cwd=str(tmp_path),
                env=service_env,
                label="receiver-entry",
            )
            process = SimpleNamespace(is_alive=lambda: supervisor.inspect(handle)["active_state"] == "active")
            deadline = time.monotonic() + 10
            while True:
                try:
                    with (socket.create_connection(("127.0.0.1", port), timeout=1) as raw,
                          RemoteNodeTransport._context().wrap_socket(raw, server_hostname="receiver")):
                        break
                except OSError:
                    if handle.process.poll() is not None:
                        error = handle.process.stderr.read().decode(errors="replace")[-4096:]
                        raise RuntimeError(
                            "installed receiver exited before readiness: " + error
                        ) from None
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
        else:
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            process = context.Process(
                target=serve,
                args=(process_config.runtime, ready,
                      authority.receiver_transport.current_authority, native_no_model),
            )
            process.start()
            assert ready.wait(10)
        service = DeliveryService(authority, {"receiver-endpoint": adapter})
        service.bind_endpoint(
            command(authority, "message.bind", "message", "receiver-endpoint"),
            EndpointBindingRequest(
                scope_id="local-scope", agent_slot_id="local-slot",
                expires_at=datetime.now(UTC) + timedelta(seconds=80),
            ),
        )
        yield SimpleNamespace(
            authority=authority, service=service, process=process,
            supervisor=supervisor, handle=handle, process_config=process_config,
            config_path=config_path,
        )
    finally:
        if supervisor is not None and handle is not None:
            termination_proof = supervisor.terminate_tree(handle)
            assert termination_proof["verified"] and termination_proof["active_state"] == "inactive"
            assert termination_proof["remaining_pids"] == [] and termination_proof["wrapper_exited"]
            if os.getenv("ACS_RECEIVER_SYSTEMD_EVIDENCE"):
                path = os.environ["ACS_RECEIVER_SYSTEMD_EVIDENCE"]
                prior = json.loads(Path(path).read_text()) if Path(path).exists() else {}
                prior["termination"] = termination_proof
                Path(path).write_text(json.dumps(prior, sort_keys=True), encoding="utf-8")
            supervisor.close()
        elif process is not None:
            process.terminate()
            process.join(5)
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_committed_registration_drives_remote_delivery(integrated):
    authority, service, process = integrated.authority, integrated.service, integrated.process
    authority.create_work_item(
        command(authority, "work_item.create", "work_item", "receiver-work"),
        "local-scope", "local-slot", "receiver-baseline",
    )
    message_command = command(authority, "message.send", "message", "receiver-message")
    packet = DeliveryPacket(
        work_item_id="receiver-work", target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="Exercise authenticated receiver", accepted_state_summary="genesis",
        request="no model invocation", source_baseline="receiver-baseline",
        expected_response="receiver ACK", activation="invoke",
        deadline=datetime.now(UTC) + timedelta(seconds=60), maximum_attempts=1,
    )
    queued = service.send_message(
        message_command, packet, endpoint_id="receiver-endpoint", binding_revision=1,
    )
    result = DeliveryDispatcher(service).dispatch({
        "tenant_id": authority.tenant_id,
        "message_id": message_command.target_id,
        "operation_id": queued.operation_id,
    })
    assert result["status"] == "delivered"
    assert process.is_alive()
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT receipt_high_water FROM delivery_messages WHERE message_id='receiver-message'"
        ).fetchone() == ("runtime_acknowledged",)
        assert connection.execute(
            "SELECT purpose,state,count(*) FROM delivery_transport_admissions "
            "GROUP BY purpose,state ORDER BY purpose"
        ).fetchall() == [
            ("delivery.dispatch", "completed", 1),
            ("delivery.prepare", "prepared", 1),
        ]
        assert connection.execute(
            "SELECT count(*) FROM delivery_receiver_receipts"
        ).fetchone() == (2,)


def test_actual_temporal_run_drives_committed_remote_delivery(integrated):
    endpoint = os.getenv("ACS_P1_TEMPORAL_ENDPOINT")
    namespace = os.getenv("ACS_P1_TEMPORAL_NAMESPACE")
    if not endpoint or not namespace:
        pytest.skip("actual Temporal endpoint and namespace required")
    authority, service, process = integrated.authority, integrated.service, integrated.process
    authority.create_work_item(
        command(authority, "work_item.create", "work_item", "temporal-receiver-work"),
        "local-scope", "local-slot", "receiver-baseline",
    )
    message_command = command(authority, "message.send", "message", "temporal-receiver-message")
    packet = DeliveryPacket(
        work_item_id="temporal-receiver-work", target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="Temporal authenticated receiver", accepted_state_summary="genesis",
        request="no model invocation", source_baseline="receiver-baseline",
        expected_response="receiver ACK", activation="invoke",
        deadline=datetime.now(UTC) + timedelta(seconds=60), maximum_attempts=1,
    )
    queued = service.send_message(
        message_command, packet, endpoint_id="receiver-endpoint", binding_revision=1,
    )
    identity = {
        "tenant_id": authority.tenant_id,
        "message_id": message_command.target_id,
        "operation_id": queued.operation_id,
    }
    dispatcher = DeliveryDispatcher(service)

    async def exercise():
        client = await Client.connect(endpoint, namespace=namespace)
        task_queue = "receiver-integration-" + uuid.uuid4().hex
        worker = delivery_worker(client, task_queue, dispatcher)
        async with worker:
            handle = await submit_delivery(client, task_queue, dispatcher, identity)
            return await handle.result()

    result = asyncio.run(exercise())
    assert result["status"] == "delivered"
    assert process.is_alive()
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT provider_run_id IS NOT NULL FROM operations WHERE operation_id=%s",
            (queued.operation_id,),
        ).fetchone() == (True,)
        assert connection.execute(
            "SELECT receipt_high_water FROM delivery_messages WHERE message_id=%s",
            (message_command.target_id,),
        ).fetchone() == ("runtime_acknowledged",)


def test_surface_receiver_management_uses_shared_auth_and_dedup(integrated):
    authority, service = integrated.authority, integrated.service
    secret = "receiver-surface-secret"
    context = replace(
        authority.context, credential_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    surface_authority = DomainAuthority(
        authority._dsn, context=context, delivery_endpoints=service.endpoints,
    )
    shared = SharedService(surface_authority, LocalCredentialAuthenticator(context))
    now = datetime.now(UTC)
    signing_key = SigningKey.generate()
    request = SurfaceCommand(
        command_type="receiver.key.register", target_id="authority-key-2",
        target_kind="authority_transport_key", expected_revision=1,
        command_id="receiver-surface-key-command", idempotency_key="receiver-surface-key-idempotency",
        correlation_id="receiver-surface", issued_at=now,
        deadline=now + timedelta(minutes=1),
        payload={
            "key_id": "authority-key-2", "revision": 2,
            "public_key": public_key(signing_key),
            "expires_at": (now + timedelta(minutes=2)).isoformat(),
        },
    )
    first = shared.handle(request, secret)
    second = shared.handle(request, secret)
    denied = shared.handle(request, "wrong-secret")
    assert first.ok and second.ok and second.result["duplicate"] is True
    assert denied.ok is False and denied.error.code == "UNAUTHENTICATED"
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT key_id,status FROM authority_transport_keys ORDER BY revision"
        ).fetchall() == [("authority-key-1", "retired"), ("authority-key-2", "active")]


def test_installed_entry_runs_in_systemd_and_handles_signed_lifecycle(integrated):
    if integrated.supervisor is None:
        pytest.skip("ACS_INSTALLED_RECEIVER is required for the actual console-script test")
    authority, service = integrated.authority, integrated.service
    authority.create_work_item(
        command(authority, "work_item.create", "work_item", "entry-work"),
        "local-scope", "local-slot", "entry-baseline",
    )
    message_command = command(authority, "message.send", "message", "entry-message")
    packet = DeliveryPacket(
        work_item_id="entry-work", target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="Installed receiver entry", accepted_state_summary="genesis",
        request="signed no-model lifecycle", source_baseline="entry-baseline",
        expected_response="receiver ACK", activation="invoke",
        deadline=datetime.now(UTC) + timedelta(seconds=60), maximum_attempts=1,
    )
    queued = service.send_message(
        message_command, packet, endpoint_id="receiver-endpoint", binding_revision=1,
    )
    observed = DeliveryDispatcher(service).dispatch({
        "tenant_id": authority.tenant_id,
        "message_id": message_command.target_id,
        "operation_id": queued.operation_id,
    })
    assert observed["status"] == "delivered"
    readback = service.endpoints["receiver-endpoint"].inspect_delivery(queued.operation_id)
    assert readback["status"] == "delivered"
    proof = integrated.supervisor.inspect(integrated.handle)
    assert proof["verified"] and proof["active_state"] == "active"
    assert proof["main_pid"] in proof["remaining_pids"]
    if os.getenv("ACS_RECEIVER_SYSTEMD_EVIDENCE"):
        Path(os.environ["ACS_RECEIVER_SYSTEMD_EVIDENCE"]).write_text(json.dumps({
            "active": proof,
            "deployment_policy_sha256": integrated.process_config.deployment_policy_sha256,
            "endpoint_id": "receiver-endpoint", "runtime_id": "receiver-runtime",
            "signed_lifecycle": ["delivery.prepare", "delivery.dispatch", "delivery.readback"],
            "model_invoked": False,
        }, sort_keys=True), encoding="utf-8")
    with authority._connect() as connection:
        assert connection.execute(
            "SELECT purpose,count(*) FROM delivery_transport_admissions GROUP BY purpose ORDER BY purpose"
        ).fetchall() == [
            ("delivery.dispatch", 1),
            ("delivery.prepare", 1),
            ("delivery.readback", 1),
        ]

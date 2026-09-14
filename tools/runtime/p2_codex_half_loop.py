"""Provision and execute the first real Windows-to-Linux P2 Codex half loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from nacl.signing import SigningKey
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
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
from runtime.receiver_crypto import public_key, sign, tls_fingerprint
from runtime.receiver_delivery import (
    ReceiverDeployment,
    RemoteNodeEndpointAdapter,
    RemoteSenderDeployment,
)
from runtime.receiver_deployment import (
    FactoryBinding,
    bind_process_config,
    dump_process_config,
)
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import EndpointBinding, EndpointRegistration


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    if os.name == "posix":
        path.chmod(0o600)


def _command(domain, kind, target_kind, target_id, *, revision=0, suffix=""):
    now = datetime.now(UTC)
    identity = suffix or uuid.uuid4().hex
    return CommandEnvelope(
        command_id=f"p2-half-{kind}-{identity}",
        idempotency_key=f"p2-half-key-{kind}-{identity}",
        command_type=kind,
        correlation_id="p2-codex-windows-linux-half-loop",
        tenant_id=domain.tenant_id,
        authority_id=domain.context.authority_id,
        authority_incarnation=domain.context.authority_incarnation,
        principal_ref=domain.context.principal_ref,
        grant_ref=domain.context.grant_ref,
        target_kind=target_kind,
        target_id=target_id,
        expected_revision=revision,
        issued_at=now,
        deadline=now + timedelta(minutes=8),
    )


def _proof(node_domain, node_key, node_id, purpose_command, node_input, *, ttl_seconds=120):
    challenge = node_domain.challenge_node(
        _command(node_domain, "node.challenge", "node", node_id, revision=1),
        NodeChallengeRequest(
            purpose=purpose_command.command_type,
            purpose_command_id=purpose_command.command_id,
            purpose_hash=EnrollmentAuthority.signing_hash(purpose_command, node_input),
            ttl_seconds=ttl_seconds,
        ),
    )
    return NodeCommandProof(
        challenge_id=challenge.challenge_id,
        signature=node_key.sign(bytes.fromhex(challenge.message_hex)).signature.hex(),
    )


def _certificate(output: Path, host: str) -> tuple[Path, Path, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acs-p2-receiver")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=4))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("receiver")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = output / "receiver-cert.pem"
    key_path = output / "receiver-tls-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    cert_path.chmod(0o600)
    key_path.chmod(0o600)
    return cert_path, key_path, tls_fingerprint(cert.public_bytes(serialization.Encoding.DER))


def provision(arguments) -> int:
    if (arguments.listen_host is None) != (arguments.listen_port is None):
        raise ValueError("listener override requires host and port")
    output = arguments.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = _json(arguments.profile)["postgres_dsn"]
    schema_name = "p2_half_" + arguments.run_suffix
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    dsn = make_conninfo(base, options=f"-c search_path={schema_name} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "work_item.read", "enrollment.manage", "receiver.manage",
        "delivery.manage", "message.send", "message.read", "runtime.invoke",
    ))
    node = DomainAuthority(dsn, context=replace(
        authority.context,
        principal_ref=f"p2-linux-node:{arguments.run_suffix}",
        grant_ref=f"grant:p2-linux-node:{arguments.run_suffix}",
    ))
    node.bootstrap_local_grant((
        "runtime.register", "attempt.register", "execution.record", "endpoint.register",
        "delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover",
        "work_item.read",
    ))
    node_key = SigningKey.generate()
    authority_key = SigningKey.generate()
    node_seed = output / "node-signing.seed"
    authority_seed = output / "authority-signing.seed"
    node_seed.write_text(node_key.encode().hex())
    authority_seed.write_text(authority_key.encode().hex())
    node_seed.chmod(0o600)
    authority_seed.chmod(0o600)
    node_id = f"linux-node-{arguments.run_suffix}"
    runtime_id = _json(arguments.factory_settings)["runtime_id"]
    boot = f"linux-boot-{arguments.run_suffix}"
    expiry = datetime.now(UTC) + timedelta(hours=2)
    authority.enroll_node(
        _command(authority, "node.enroll", "node", node_id),
        NodeEnrollment(
            scope_id="local-scope", agent_slot_id="local-slot",
            observer_grant_ref=node.context.grant_ref,
            machine_id=arguments.linux_machine_id, boot_incarnation=boot,
            public_key=public_key(node_key), expires_at=expiry,
        ),
    )
    runtime_request = RuntimeRegistration(
        node_id=node_id, node_binding_revision=1, provider="codex-app-server",
        producer_grant_ref=authority.context.grant_ref,
        expires_at=expiry - timedelta(minutes=5),
    )
    runtime_command = _command(node, "runtime.register", "runtime", runtime_id)
    node.register_runtime(
        runtime_command, runtime_request,
        _proof(node, node_key, node_id, runtime_command,
               {"request": runtime_request.model_dump(mode="json")}),
    )
    authority_key_id = f"p2-authority-key-{arguments.run_suffix}"
    authority.register_authority_transport_key(
        _command(authority, "receiver.key.register", "authority_transport_key", authority_key_id),
        AuthorityTransportKeyRegistration(
            key_id=authority_key_id, revision=1, public_key=public_key(authority_key),
            expires_at=expiry - timedelta(minutes=5),
        ),
    )
    connection_ref = f"p2-linux-private-{arguments.run_suffix}"
    authority.register_receiver_connection(
        _command(authority, "receiver.connection.register", "connection", connection_ref),
        ConnectionReferenceRegistration(
            connection_ref=connection_ref, revision=1,
            locator_host=arguments.linux_host, locator_port=arguments.port,
            route_class=arguments.route_class, policy_digest=arguments.source_tree.ljust(64, "0")[:64],
            expires_at=expiry - timedelta(minutes=5),
        ),
    )
    cert_path, tls_key_path, cert_hash = _certificate(output, arguments.linux_host)
    with authority._connect() as connection:
        node_key_id = connection.execute(
            "SELECT key_id FROM enrolled_node_bindings WHERE tenant_id=%s AND node_id=%s "
            "AND binding_revision=1", (authority.tenant_id, node_id),
        ).fetchone()[0]
    endpoint_id = f"p2-linux-endpoint-{arguments.run_suffix}"
    provisional = EndpointRegistration(
        registration_id=f"p2-linux-registration-{arguments.run_suffix}",
        endpoint_id=endpoint_id, endpoint_revision=1, connection_ref=connection_ref,
        tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        node_id=node_id, node_binding_revision=1, runtime_id=runtime_id,
        runtime_revision=1, machine_id=arguments.linux_machine_id,
        boot_incarnation=boot, scope_id="local-scope", agent_slot_id="local-slot",
        tls_certificate_sha256=cert_hash, config_sha256="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=4),
    )
    binding = EndpointBinding(
        registration=provisional, locator_host=arguments.linux_host,
        locator_port=arguments.port, route_class=arguments.route_class, node_key_id=node_key_id,
        node_public_key=public_key(node_key), registration_signature=sign(node_key, provisional),
    )
    provisional_config = ReceiverRuntimeConfig(
        binding=binding, authority_key_id=authority_key_id, authority_key_revision=1,
        authority_public_key=public_key(authority_key),
        authority_public_key_fingerprint=hashlib.sha256(
            bytes.fromhex(public_key(authority_key))
        ).hexdigest(),
        tls_cert_path=str(cert_path), tls_key_path=str(tls_key_path),
        node_signing_key_path=str(node_seed), ledger_path=str(output / "receiver.sqlite"),
        expected_boot_incarnation=boot, journal_generation=1,
        drop_response_after_commit_once=arguments.drop_response,
    )
    if arguments.listen_host is not None:
        provisional_config = replace(
            provisional_config, listen_host=arguments.listen_host,
            listen_port=arguments.listen_port,
        )
    factory = FactoryBinding.model_validate(_json(arguments.factory_binding), strict=True)
    process = bind_process_config(provisional_config, factory, node_key)
    registration = process.runtime.binding.registration
    endpoint_command = _command(node, "endpoint.register", "endpoint", endpoint_id)
    node_input = {
        "registration": registration.model_dump(mode="json"),
        "registration_signature": process.runtime.binding.registration_signature,
    }
    node.register_receiver_endpoint(
        endpoint_command,
        EndpointRegistrationCommand(
            registration=registration,
            registration_signature=process.runtime.binding.registration_signature,
            proof=_proof(
                node, node_key, node_id, endpoint_command, node_input, ttl_seconds=300,
            ),
        ),
    )
    _write(output / "receiver-process.json", json.loads(dump_process_config(process)))
    public = {
        "schema_version": "acs-p2-codex-half-loop-state/1",
        "run_suffix": arguments.run_suffix,
        "schema_name": schema_name,
        "source_commit": arguments.source_commit,
        "source_tree": arguments.source_tree,
        "linux_host": arguments.linux_host,
        "linux_machine_id": arguments.linux_machine_id,
        "node_id": node_id,
        "boot_incarnation": boot,
        "runtime_id": runtime_id,
        "endpoint_id": endpoint_id,
        "endpoint_revision": 1,
        "connection_ref": connection_ref,
        "receiver_process_sha256": hashlib.sha256(
            (output / "receiver-process.json").read_bytes()
        ).hexdigest(),
        "factory_binding_sha256": hashlib.sha256(arguments.factory_binding.read_bytes()).hexdigest(),
        "factory_settings_sha256": hashlib.sha256(arguments.factory_settings.read_bytes()).hexdigest(),
        "tls_certificate_sha256": cert_hash,
    }
    _write(output / "state.json", public)
    print(json.dumps(public, sort_keys=True))
    return 0


def execute(arguments) -> int:
    state = _json(arguments.state)
    base = _json(arguments.windows_profile)["postgres_dsn"]
    dsn = make_conninfo(base, options=f"-c search_path={state['schema_name']} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    with authority._connect() as connection:
        key = connection.execute(
            "SELECT public_key FROM authority_transport_keys WHERE tenant_id=%s "
            "AND status='active'", (authority.tenant_id,),
        ).fetchone()[0]
    signing_key = SigningKey(bytes.fromhex(arguments.authority_seed.read_text().strip()))
    if public_key(signing_key) != key:
        raise RuntimeError("Windows authority signing key differs from Domain registration")
    sender = RemoteSenderDeployment(
        authority_signing_key=signing_key,
        expected_boot_incarnation=state["boot_incarnation"],
        journal_generation=1,
    )
    endpoint = RemoteNodeEndpointAdapter(authority, state["endpoint_id"], sender, timeout=10)
    service = DeliveryService(authority, {state["endpoint_id"]: endpoint})
    service.bind_endpoint(
        _command(authority, "message.bind", "message", state["endpoint_id"]),
        EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="local-slot",
            expires_at=datetime.now(UTC) + timedelta(minutes=40),
        ),
    )
    work_id = f"p2-half-work-{state['run_suffix']}"
    authority.create_work_item(
        _command(authority, "work_item.create", "work_item", work_id),
        "local-scope", "local-slot", state["source_commit"],
    )
    message_id = f"p2-half-message-{state['run_suffix']}"
    message_command = _command(authority, "message.send", "message", message_id)
    sentinel = "P2-CODEX-WINDOWS-TO-LINUX-" + state["run_suffix"]
    packet = DeliveryPacket(
        work_item_id=work_id, target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="Prove one authenticated Windows-to-Linux P2 Codex Runtime delivery",
        accepted_state_summary="P1 passed; P2 remains blocked until both directions pass",
        request=(
            "Return exactly this sentinel and no other text: " + sentinel
            + ". Do not call tools and do not delegate."
        ),
        constraints=("one native Codex turn", "no delegation", "no tool calls"),
        source_baseline=state["source_commit"],
        context_digests=(state["source_tree"].ljust(64, "0")[:64],),
        expected_response=sentinel,
        required_evidence=("PostgreSQL", "receiver SQLite", "Driver journal", "Node outbox"),
        activation="invoke", deadline=datetime.now(UTC) + timedelta(minutes=5),
        maximum_attempts=1, retry_delay_seconds=1,
    )
    queued = service.send_message(
        message_command, packet, endpoint_id=state["endpoint_id"], binding_revision=1,
    )
    result = DeliveryDispatcher(service, worker_id="windows-p2-sender").dispatch({
        "tenant_id": authority.tenant_id,
        "message_id": message_id,
        "operation_id": queued.operation_id,
    })
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with authority._connect() as connection:
            high = connection.execute(
                "SELECT state,receipt_high_water FROM delivery_messages WHERE tenant_id=%s "
                "AND message_id=%s", (authority.tenant_id, message_id),
            ).fetchone()
        if high and high[1] == "response_received":
            break
        time.sleep(1)
    with authority._connect() as connection:
        message = connection.execute(
            "SELECT state,receipt_high_water,attempts,activation_node_id,activation_machine_id "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
            (authority.tenant_id, message_id),
        ).fetchone()
        receipts = connection.execute(
            "SELECT layer,receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
            "ORDER BY observed_at", (authority.tenant_id, message_id),
        ).fetchall()
        attempt = connection.execute(
            "SELECT attempt_id,dispatch_id,invocation_json,status FROM delivery_attempts "
            "WHERE tenant_id=%s AND message_id=%s", (authority.tenant_id, message_id),
        ).fetchone()
        response = connection.execute(
            "SELECT projection_id,native_response_ref,response_artifact_ref,response_digest,"
            "evidence_digest,disposition FROM native_response_observations WHERE tenant_id=%s "
            "AND invocation_id=%s", (authority.tenant_id, attempt[2]["invocation_id"]),
        ).fetchone()
    evidence = {
        "schema_version": "acs-p2-codex-half-loop-evidence/1",
        "status": "blocked",
        "reason": "Windows-to-Linux half loop only; reverse registered receiver direction not run",
        "source_commit": state["source_commit"],
        "source_tree": state["source_tree"],
        "windows_sender_machine": arguments.windows_machine_id,
        "linux_receiver_machine": state["linux_machine_id"],
        "runtime_transport": "direct TLS 1.3 to registered private endpoint",
        "control_transport": "SSH used only for deployment/process control",
        "dispatch_result": result,
        "message": list(message) if message else None,
        "receipts": [list(row) for row in receipts],
        "attempt": [attempt[0], attempt[1], attempt[3]] if attempt else None,
        "response_projection": list(response) if response else None,
        "expected_sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
        "message_id": message_id,
        "operation_id": queued.operation_id,
        "endpoint_id": state["endpoint_id"],
    }
    _write(arguments.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if response and message and message[1] == "response_received" else 2


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("provision")
    setup.add_argument("--profile", type=Path, required=True)
    setup.add_argument("--factory-binding", type=Path, required=True)
    setup.add_argument("--factory-settings", type=Path, required=True)
    setup.add_argument("--output", type=Path, required=True)
    setup.add_argument("--run-suffix", required=True)
    setup.add_argument("--source-commit", required=True)
    setup.add_argument("--source-tree", required=True)
    setup.add_argument("--linux-host", required=True)
    setup.add_argument("--linux-machine-id", required=True)
    setup.add_argument("--port", type=int, required=True)
    setup.add_argument("--route-class", choices=("private", "tunnel"), default="private")
    setup.add_argument("--listen-host")
    setup.add_argument("--listen-port", type=int)
    setup.add_argument(
        "--drop-response",
        choices=("delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover"),
    )
    run = sub.add_parser("execute")
    run.add_argument("--windows-profile", type=Path, required=True)
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--authority-seed", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--windows-machine-id", required=True)
    args = parser.parse_args(argv)
    return provision(args) if args.action == "provision" else execute(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Same-run P1 identity-continuity Gate qualification.

The component auditor remains deliberately unable to emit a Gate pass. This
adapter composes the real Domain enrollment and receiver transport, receiver
SQLite, prepared-attempt recovery, Temporal delivery Workflow, and owned OS
processes around one WorkItem, Message, Attempt, and operation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import socket
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.signing import SigningKey
from psycopg.conninfo import make_conninfo
from temporalio.client import Client
from temporalio.worker import Worker

from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_temporal import CommittedDeliveryWorkflow, submit_delivery
from runtime.domain import DomainAuthority
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    AttemptRegistration,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    NodeRotation,
    RuntimeRegistration,
)
from runtime.receiver import ReceiverLedger
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import key_fingerprint, public_key, sign, tls_fingerprint
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import (
    EndpointBinding,
    EndpointRegistration,
    SignedReceipt,
    SignedRequest,
)
from runtime.remote_endpoint import RemoteNodeTransport, serve
from runtime.temporal import TemporalAdapter
from tools.runtime.p1_identity_continuity_probe import (
    AttemptReadback,
    ContinuityRejected,
    LogicalIdentity,
    NodeBootReadback,
    audit_component_chain,
    read_receiver_ledger,
)

SCENARIO = "P1-IDENTITY-CONTINUITY"
_LAYERS = ("postgresql", "sqlite", "temporal", "os")


class IdentityContinuityRejected(RuntimeError):
    pass


class PreparedRecoveryDispatcher(DeliveryDispatcher):
    """Temporal activity adapter for one already prepared receiver Attempt."""

    def dispatch(self, identity):
        return self.recover_prepared(identity)


class CrashingRecoveryDispatcher(PreparedRecoveryDispatcher):
    """First Provider Worker fault: exit before the Attempt is resumed."""

    def dispatch(self, _identity):
        os._exit(84)


@dataclass(slots=True)
class SceneResources:
    authority: DomainAuthority
    observer: DomainAuthority
    service: DeliveryService
    endpoint_id: str
    old_runtime_id: str
    new_runtime_id: str
    old_boot: str
    new_boot: str
    authority_key_id: str
    authority_key: SigningKey
    old_node_key: SigningKey
    new_node_key: SigningKey
    old_binding: EndpointBinding
    old_config: ReceiverRuntimeConfig
    old_receiver: multiprocessing.Process | None
    receiver_ledger: Path
    node_seed: Path
    cert_path: Path
    tls_key_path: Path
    cert_der_path: Path
    certificate_sha256: str
    mutation_command_ids: list[str]
    signed_command_ids: list[str]
    domain_command: Callable[..., Any]
    issued_at: datetime
    suffix: str
    new_binding: EndpointBinding | None = None
    new_config: ReceiverRuntimeConfig | None = None
    new_receiver: multiprocessing.Process | None = None


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _canonical(value)).hexdigest()


def _free_port() -> int:
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


def _pid_live(pid: int) -> bool:
    return type(pid) is int and pid > 0 and Path(f"/proc/{pid}").exists()


def _port_closed(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return False
    except OSError:
        return True


def _native_invoke(admission) -> dict[str, Any]:
    return {
        "native_ack_ref": "identity-continuity:" + admission.dispatch_id,
        "model_invoked": False,
    }


def _certificate(root: Path) -> tuple[Path, Path, Path, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acs-p1-receiver")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("receiver")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = root / "receiver-cert.pem"
    key_path = root / "receiver-tls-key.pem"
    der_path = root / "receiver-peer-certificate.der"
    der = cert.public_bytes(serialization.Encoding.DER)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    der_path.write_bytes(der)
    for path in (cert_path, key_path, der_path):
        path.chmod(0o600)
    return cert_path, key_path, der_path, tls_fingerprint(der)


def _start_receiver(config: ReceiverRuntimeConfig, authority: DomainAuthority):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(
        target=serve,
        args=(
            config,
            ready,
            authority.receiver_transport.current_authority,
            _native_invoke,
        ),
    )
    process.start()
    if not ready.wait(10) or not process.is_alive():
        process.join(2)
        raise IdentityContinuityRejected("signed TLS receiver did not become ready")
    return process


def _stop_owned(process: multiprocessing.Process | None, label: str) -> None:
    if process is None:
        return
    if process.is_alive():
        process.terminate()
        process.join(10)
    if process.is_alive():
        process.kill()
        process.join(3)
    if process.is_alive():
        raise IdentityContinuityRejected(f"owned {label} process remains live")


def _tls_readback(binding: EndpointBinding) -> dict[str, Any]:
    context = RemoteNodeTransport._context()
    with (
        socket.create_connection((binding.locator_host, binding.locator_port), timeout=3) as raw,
        context.wrap_socket(raw, server_hostname="receiver") as tls,
    ):
        certificate = tls.getpeercert(binary_form=True)
        version = tls.version()
    observed = tls_fingerprint(certificate)
    if observed != binding.registration.tls_certificate_sha256:
        raise IdentityContinuityRejected("receiver TLS fingerprint changed")
    return {"version": version, "certificate_sha256": observed}


def _node_proof(
    observer: DomainAuthority,
    node_key: SigningKey,
    node_id: str,
    purpose_command,
    node_input: dict[str, Any],
    *,
    domain_command,
    suffix: str,
    issued_at: datetime,
    revision: int,
) -> NodeCommandProof:
    challenge_command = domain_command(
        observer,
        "node.challenge",
        "node",
        node_id,
        suffix + ":challenge:" + purpose_command.command_type,
        issued_at,
        revision=revision,
    )
    challenge = observer.challenge_node(
        challenge_command,
        NodeChallengeRequest(
            purpose=purpose_command.command_type,
            purpose_command_id=purpose_command.command_id,
            purpose_hash=EnrollmentAuthority.signing_hash(purpose_command, node_input),
            ttl_seconds=300,
        ),
    )
    return NodeCommandProof(
        challenge_id=challenge.challenge_id,
        signature=node_key.sign(bytes.fromhex(challenge.message_hex)).signature.hex(),
    )


def _endpoint_binding(
    authority: DomainAuthority,
    node_key: SigningKey,
    *,
    endpoint_id: str,
    endpoint_revision: int,
    connection_ref: str,
    port: int,
    node_id: str,
    node_binding_revision: int,
    runtime_id: str,
    machine_id: str,
    boot: str,
    certificate_sha256: str,
    expires_at: datetime,
    suffix: str,
) -> EndpointBinding:
    with authority._connect() as connection:
        key_id = connection.execute(
            "SELECT key_id FROM enrolled_node_bindings WHERE tenant_id=%s AND node_id=%s "
            "AND binding_revision=%s",
            (authority.tenant_id, node_id, node_binding_revision),
        ).fetchone()[0]
    registration = EndpointRegistration(
        registration_id=f"identity-registration-{endpoint_revision}-{suffix}",
        endpoint_id=endpoint_id,
        endpoint_revision=endpoint_revision,
        connection_ref=connection_ref,
        tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        node_id=node_id,
        node_binding_revision=node_binding_revision,
        runtime_id=runtime_id,
        runtime_revision=1,
        machine_id=machine_id,
        boot_incarnation=boot,
        scope_id="local-scope",
        agent_slot_id="local-slot",
        tls_certificate_sha256=certificate_sha256,
        config_sha256=_hash({
            "endpoint_id": endpoint_id,
            "endpoint_revision": endpoint_revision,
            "runtime_id": runtime_id,
            "boot": boot,
        }),
        expires_at=expires_at,
    )
    return EndpointBinding(
        registration=registration,
        locator_host="127.0.0.1",
        locator_port=port,
        route_class="loopback",
        node_key_id=key_id,
        node_public_key=public_key(node_key),
        registration_signature=sign(node_key, registration),
    )


def _register_endpoint(
    resources: SceneResources,
    binding: EndpointBinding,
    node_key: SigningKey,
    *,
    suffix: str,
) -> None:
    registration = binding.registration
    command = resources.domain_command(
        resources.observer,
        "endpoint.register",
        "endpoint",
        registration.endpoint_id,
        suffix,
        resources.issued_at,
        revision=registration.endpoint_revision - 1,
    )
    node_input = {
        "registration": registration.model_dump(mode="json"),
        "registration_signature": binding.registration_signature,
    }
    resources.observer.register_receiver_endpoint(
        command,
        EndpointRegistrationCommand(
            registration=registration,
            registration_signature=binding.registration_signature,
            proof=_node_proof(
                resources.observer,
                node_key,
                registration.node_id,
                command,
                node_input,
                domain_command=resources.domain_command,
                suffix=suffix,
                issued_at=resources.issued_at,
                revision=registration.node_binding_revision,
            ),
        ),
    )
    resources.mutation_command_ids.append(command.command_id)
    resources.signed_command_ids.append(command.command_id)


def provision(
    authority: DomainAuthority,
    ledger,
    *,
    endpoint_id: str,
    machine_id: str,
    node_id: str,
    suffix: str,
    issued_at: datetime,
    domain_command,
) -> SceneResources:
    """Commit the first signed Node/Runtime/endpoint before Message admission."""
    receiver_root = ledger.root / f"{SCENARIO}-receiver"
    receiver_root.mkdir(mode=0o700, exist_ok=True)
    receiver_ledger = receiver_root / "receiver.sqlite"
    node_seed = receiver_root / "node-signing.seed"
    cert_path, tls_key_path, cert_der_path, certificate_sha256 = _certificate(receiver_root)
    authority_key = SigningKey.generate()
    old_node_key = SigningKey.generate()
    new_node_key = SigningKey.generate()
    node_seed.write_text(old_node_key.encode().hex(), encoding="ascii")
    node_seed.chmod(0o600)
    expiry = datetime.now(UTC) + timedelta(minutes=20)
    observer = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-identity-node:" + suffix,
        grant_ref="grant:p1-identity-node:" + suffix,
    ))
    observer.bootstrap_local_grant((
        "runtime.register", "attempt.register", "execution.record", "endpoint.register",
        "delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover",
        "work_item.read",
    ))
    command_ids: list[str] = []
    old_boot = "identity-boot-1-" + suffix
    new_boot = "identity-boot-2-" + suffix
    old_runtime_id = "identity-runtime-1-" + suffix
    new_runtime_id = "identity-runtime-2-" + suffix
    old_connection_ref = "identity-loopback-1-" + suffix
    authority_key_id = "identity-authority-key-" + suffix

    enroll = domain_command(
        authority, "node.enroll", "node", node_id,
        suffix + ":identity-node-enroll", issued_at,
    )
    authority.enroll_node(enroll, NodeEnrollment(
        scope_id="local-scope",
        agent_slot_id="local-slot",
        observer_grant_ref=observer.context.grant_ref,
        machine_id=machine_id,
        boot_incarnation=old_boot,
        public_key=public_key(old_node_key),
        expires_at=expiry,
    ))
    command_ids.append(enroll.command_id)

    runtime_request = RuntimeRegistration(
        node_id=node_id,
        node_binding_revision=1,
        provider="p1-identity-receiver",
        producer_grant_ref=authority.context.grant_ref,
        expires_at=expiry - timedelta(minutes=1),
    )
    runtime_command = domain_command(
        observer, "runtime.register", "runtime", old_runtime_id,
        suffix + ":identity-runtime-1", issued_at,
    )
    observer.register_runtime(
        runtime_command,
        runtime_request,
        _node_proof(
            observer,
            old_node_key,
            node_id,
            runtime_command,
            {"request": runtime_request.model_dump(mode="json")},
            domain_command=domain_command,
            suffix=suffix + ":runtime-1",
            issued_at=issued_at,
            revision=1,
        ),
    )
    command_ids.append(runtime_command.command_id)

    key_command = domain_command(
        authority, "receiver.key.register", "authority_transport_key",
        authority_key_id, suffix + ":identity-authority-key", issued_at,
    )
    authority.register_authority_transport_key(
        key_command,
        AuthorityTransportKeyRegistration(
            key_id=authority_key_id,
            revision=1,
            public_key=public_key(authority_key),
            expires_at=expiry - timedelta(minutes=1),
        ),
    )
    command_ids.append(key_command.command_id)

    old_port = _free_port()
    connection_command = domain_command(
        authority, "receiver.connection.register", "connection", old_connection_ref,
        suffix + ":identity-connection-1", issued_at,
    )
    authority.register_receiver_connection(
        connection_command,
        ConnectionReferenceRegistration(
            connection_ref=old_connection_ref,
            revision=1,
            locator_host="127.0.0.1",
            locator_port=old_port,
            route_class="loopback",
            policy_digest=_hash({"connection_ref": old_connection_ref}),
            expires_at=expiry - timedelta(minutes=1),
        ),
    )
    command_ids.append(connection_command.command_id)
    old_binding = _endpoint_binding(
        authority,
        old_node_key,
        endpoint_id=endpoint_id,
        endpoint_revision=1,
        connection_ref=old_connection_ref,
        port=old_port,
        node_id=node_id,
        node_binding_revision=1,
        runtime_id=old_runtime_id,
        machine_id=machine_id,
        boot=old_boot,
        certificate_sha256=certificate_sha256,
        expires_at=datetime.now(UTC) + timedelta(minutes=4),
        suffix=suffix,
    )
    resources = SceneResources(
        authority=authority,
        observer=observer,
        service=None,  # type: ignore[arg-type]
        endpoint_id=endpoint_id,
        old_runtime_id=old_runtime_id,
        new_runtime_id=new_runtime_id,
        old_boot=old_boot,
        new_boot=new_boot,
        authority_key_id=authority_key_id,
        authority_key=authority_key,
        old_node_key=old_node_key,
        new_node_key=new_node_key,
        old_binding=old_binding,
        old_config=None,  # type: ignore[arg-type]
        old_receiver=None,
        receiver_ledger=receiver_ledger,
        node_seed=node_seed,
        cert_path=cert_path,
        tls_key_path=tls_key_path,
        cert_der_path=cert_der_path,
        certificate_sha256=certificate_sha256,
        mutation_command_ids=command_ids,
        signed_command_ids=[runtime_command.command_id],
        domain_command=domain_command,
        issued_at=issued_at,
        suffix=suffix,
    )
    _register_endpoint(
        resources, old_binding, old_node_key,
        suffix=suffix + ":identity-endpoint-1",
    )
    old_config = ReceiverRuntimeConfig(
        binding=old_binding,
        authority_key_id=authority_key_id,
        authority_key_revision=1,
        authority_public_key=public_key(authority_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        tls_cert_path=str(cert_path),
        tls_key_path=str(tls_key_path),
        node_signing_key_path=str(node_seed),
        ledger_path=str(receiver_ledger),
        expected_boot_incarnation=old_boot,
        journal_generation=1,
    )
    sender = RemoteSenderDeployment(
        authority_signing_key=authority_key,
        expected_boot_incarnation=old_boot,
        journal_generation=1,
    )
    adapter = RemoteNodeEndpointAdapter(authority, endpoint_id, sender, timeout=5)
    resources.old_config = old_config
    resources.service = DeliveryService(authority, {endpoint_id: adapter})
    return resources


def _core_crash_child(service: DeliveryService, identity: dict[str, str]) -> None:
    endpoint = next(iter(service.endpoints.values()))
    endpoint.after_prepare = lambda _invocation, _receipt: os._exit(83)
    DeliveryDispatcher(service, worker_id="identity-old-core").dispatch(identity)
    os._exit(82)


def _provider_worker_child(
    profile: dict[str, Any],
    service: DeliveryService,
    identity: dict[str, str],
    queue: str,
    workflow_id: str,
    run_id: str,
    mode: str,
    result_path: str,
) -> None:
    dispatcher = (
        CrashingRecoveryDispatcher(service, worker_id="identity-provider-crash")
        if mode == "crash"
        else PreparedRecoveryDispatcher(service, worker_id="identity-replacement-core")
    )

    async def exercise() -> None:
        adapter = TemporalAdapter(
            profile["temporal_endpoint"],
            namespace=profile["temporal_namespace"],
            task_queue=queue,
            worker_identity="identity-" + mode,
            delivery_dispatcher=dispatcher,
        )
        await adapter.connect(start_worker=True)
        try:
            if mode == "crash":
                await asyncio.sleep(120)
                raise IdentityContinuityRejected("first Temporal Worker did not reach crash seam")
            handle = adapter.client.get_workflow_handle(workflow_id, run_id=run_id)
            result = await asyncio.wait_for(handle.result(), timeout=100)
            query = dict(await handle.query("state"))
            description = await handle.describe()
            value = {
                "worker_pid": os.getpid(),
                "workflow_id": handle.id,
                "run_id": description.run_id,
                "result": dict(result),
                "query": query,
            }
            path = Path(result_path)
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600,
            )
            try:
                os.write(descriptor, _canonical(value))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            await adapter.close()

    asyncio.run(exercise())


def _submit_temporal_child(
    profile: dict[str, Any], service: DeliveryService,
    identity: dict[str, str], queue: str, result_path: str,
) -> None:
    async def submit() -> tuple[str, str]:
        adapter = TemporalAdapter(
            profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
        )
        await adapter.connect(start_worker=False)
        try:
            handle = await submit_delivery(
                adapter.client,
                queue,
                PreparedRecoveryDispatcher(service, worker_id="identity-submit"),
                identity,
            )
            description = await handle.describe()
            return handle.id, description.run_id
        finally:
            await adapter.close()

    workflow_id, run_id = asyncio.run(submit())
    path = Path(result_path)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600,
    )
    try:
        os.write(descriptor, _canonical({
            "submitter_pid": os.getpid(),
            "workflow_id": workflow_id,
            "run_id": run_id,
        }))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temporal_readback(
    profile: dict[str, Any], workflow_id: str, run_id: str,
    identity: dict[str, str], task_queue: str,
) -> dict[str, Any]:
    async def read() -> dict[str, Any]:
        client = await Client.connect(
            profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
        )
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CommittedDeliveryWorkflow],
            identity="identity-readback-query",
        )
        async with worker:
            handle = client.get_workflow_handle(workflow_id, run_id=run_id)
            description = await handle.describe()
            result = dict(await handle.result())
            query = dict(await handle.query("state"))
            memo = await description.memo()
            return {
                "workflow_id": handle.id,
                "run_id": description.run_id,
                "result": result,
                "query": query,
                "identity_hash": memo.get("acs_delivery_identity_hash"),
            }

    try:
        readback = asyncio.run(read())
    except IdentityContinuityRejected:
        raise
    except Exception as exc:
        raise IdentityContinuityRejected(
            "Temporal Workflow/Run live readback is unavailable",
        ) from exc
    expected_hash = _hash(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    if (
        readback["workflow_id"] != "acs-delivery/" + identity["operation_id"]
        or readback["workflow_id"] != workflow_id
        or readback["run_id"] != run_id
        or readback["result"].get("status") != "delivered"
        or readback["result"].get("message_id") != identity["message_id"]
        or readback["query"] != readback["result"]
        or readback["identity_hash"] != expected_hash
    ):
        raise IdentityContinuityRejected("Temporal Workflow/Run live readback changed")
    return readback


def _rotate_receiver(
    resources: SceneResources,
    *,
    work_id: str,
    attempt_id: str,
    commit: str,
    tree: str,
) -> int:
    authority = resources.authority
    observer = resources.observer
    if resources.old_receiver is None:
        raise IdentityContinuityRejected("old receiver process is unavailable")
    old_receiver_pid = resources.old_receiver.pid
    _stop_owned(resources.old_receiver, "old receiver")
    if _pid_live(old_receiver_pid):
        raise IdentityContinuityRejected("old receiver PID remains live")

    with authority._connect() as connection:
        observed_started_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    attempt_request = AttemptRegistration(
        runtime_id=resources.old_runtime_id,
        work_item_id=work_id,
        expected_work_item_revision=0,
        source_baseline=commit,
        source_commit=commit,
        source_tree=tree,
        candidate_ref="identity-candidate-" + resources.suffix,
        observed_started_at=observed_started_at,
    )
    attempt_command = resources.domain_command(
        observer, "attempt.register", "attempt", attempt_id,
        resources.suffix + ":identity-attempt-register", resources.issued_at,
    )
    observer.register_attempt(
        attempt_command,
        attempt_request,
        _node_proof(
            observer,
            resources.old_node_key,
            resources.old_binding.registration.node_id,
            attempt_command,
            {"request": attempt_request.model_dump(mode="json")},
            domain_command=resources.domain_command,
            suffix=resources.suffix + ":attempt",
            issued_at=resources.issued_at,
            revision=1,
        ),
    )
    resources.mutation_command_ids.append(attempt_command.command_id)
    resources.signed_command_ids.append(attempt_command.command_id)

    rotate = resources.domain_command(
        authority, "node.rotate", "node", resources.old_binding.registration.node_id,
        resources.suffix + ":identity-node-rotate", resources.issued_at,
        revision=1,
    )
    authority.rotate_node(rotate, NodeRotation(
        machine_id=resources.old_binding.registration.machine_id,
        boot_incarnation=resources.new_boot,
        public_key=public_key(resources.new_node_key),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    ))
    resources.mutation_command_ids.append(rotate.command_id)

    runtime_request = RuntimeRegistration(
        node_id=resources.old_binding.registration.node_id,
        node_binding_revision=2,
        provider="p1-identity-receiver-replacement",
        producer_grant_ref=authority.context.grant_ref,
        expires_at=datetime.now(UTC) + timedelta(minutes=14),
    )
    runtime_command = resources.domain_command(
        observer, "runtime.register", "runtime", resources.new_runtime_id,
        resources.suffix + ":identity-runtime-2", resources.issued_at,
    )
    observer.register_runtime(
        runtime_command,
        runtime_request,
        _node_proof(
            observer,
            resources.new_node_key,
            resources.old_binding.registration.node_id,
            runtime_command,
            {"request": runtime_request.model_dump(mode="json")},
            domain_command=resources.domain_command,
            suffix=resources.suffix + ":runtime-2",
            issued_at=resources.issued_at,
            revision=2,
        ),
    )
    resources.mutation_command_ids.append(runtime_command.command_id)
    resources.signed_command_ids.append(runtime_command.command_id)

    new_connection_ref = "identity-loopback-2-" + resources.suffix
    new_port = _free_port()
    connection_command = resources.domain_command(
        authority, "receiver.connection.register", "connection", new_connection_ref,
        resources.suffix + ":identity-connection-2", resources.issued_at,
    )
    authority.register_receiver_connection(
        connection_command,
        ConnectionReferenceRegistration(
            connection_ref=new_connection_ref,
            revision=1,
            locator_host="127.0.0.1",
            locator_port=new_port,
            route_class="loopback",
            policy_digest=_hash({"connection_ref": new_connection_ref}),
            expires_at=datetime.now(UTC) + timedelta(minutes=14),
        ),
    )
    resources.mutation_command_ids.append(connection_command.command_id)
    binding = _endpoint_binding(
        authority,
        resources.new_node_key,
        endpoint_id=resources.endpoint_id,
        endpoint_revision=2,
        connection_ref=new_connection_ref,
        port=new_port,
        node_id=resources.old_binding.registration.node_id,
        node_binding_revision=2,
        runtime_id=resources.new_runtime_id,
        machine_id=resources.old_binding.registration.machine_id,
        boot=resources.new_boot,
        certificate_sha256=resources.certificate_sha256,
        expires_at=datetime.now(UTC) + timedelta(minutes=4),
        suffix=resources.suffix,
    )
    _register_endpoint(
        resources, binding, resources.new_node_key,
        suffix=resources.suffix + ":identity-endpoint-2",
    )
    resources.node_seed.write_text(resources.new_node_key.encode().hex(), encoding="ascii")
    resources.node_seed.chmod(0o600)
    config = ReceiverRuntimeConfig(
        binding=binding,
        authority_key_id=resources.authority_key_id,
        authority_key_revision=1,
        authority_public_key=public_key(resources.authority_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(resources.authority_key)),
        tls_cert_path=str(resources.cert_path),
        tls_key_path=str(resources.tls_key_path),
        node_signing_key_path=str(resources.node_seed),
        ledger_path=str(resources.receiver_ledger),
        expected_boot_incarnation=resources.new_boot,
        journal_generation=2,
        old_boot_isolation_ref=f"pid:{old_receiver_pid}:exited",
        drop_response_after_commit_once="delivery.recover",
    )
    resources.new_binding = binding
    resources.new_config = config
    resources.new_receiver = _start_receiver(config, authority)
    sender = RemoteSenderDeployment(
        authority_signing_key=resources.authority_key,
        expected_boot_incarnation=resources.new_boot,
        journal_generation=2,
        old_boot_isolation_ref=config.old_boot_isolation_ref,
    )
    adapter = RemoteNodeEndpointAdapter(authority, resources.endpoint_id, sender, timeout=5)
    resources.service.endpoints[resources.endpoint_id] = adapter
    bind = resources.domain_command(
        authority, "message.bind", "message", resources.endpoint_id,
        resources.suffix + ":identity-bind-2", resources.issued_at,
        revision=1,
    )
    resources.service.bind_endpoint(bind, EndpointBindingRequest(
        scope_id="local-scope",
        agent_slot_id="local-slot",
        expires_at=bind.deadline,
    ))
    resources.mutation_command_ids.append(bind.command_id)
    return old_receiver_pid


def _signed_exchange_rows(
    authority: DomainAuthority, operation_id: str, receiver_ledger: Path,
) -> dict[str, tuple[SignedRequest, SignedReceipt]]:
    with authority._connect() as connection:
        requests = connection.execute(
            "SELECT purpose,signed_request_json FROM delivery_transport_admissions "
            "WHERE operation_id=%s ORDER BY recorded_at",
            (operation_id,),
        ).fetchall()
    request_by_purpose = {
        row[0]: SignedRequest.model_validate_json(json.dumps(row[1]), strict=True)
        for row in requests
    }
    with sqlite3.connect(receiver_ledger) as connection:
        receipts = connection.execute(
            "SELECT purpose,receipt_json FROM receiver_requests WHERE operation_id=? "
            "AND purpose IN ('delivery.prepare','delivery.recover') ORDER BY created_at",
            (operation_id,),
        ).fetchall()
    receipt_by_purpose = {
        row[0]: SignedReceipt.model_validate_json(row[1], strict=True) for row in receipts
    }
    if set(request_by_purpose) < {"delivery.prepare", "delivery.recover"} or set(
        receipt_by_purpose
    ) != {"delivery.prepare", "delivery.recover"}:
        raise IdentityContinuityRejected("signed prepare/recovery exchange is incomplete")
    return {
        purpose: (request_by_purpose[purpose], receipt_by_purpose[purpose])
        for purpose in ("delivery.prepare", "delivery.recover")
    }


def _pg_readback(profile: dict[str, Any], pg_schema: str, proof: dict[str, Any]) -> dict[str, Any]:
    scoped = make_conninfo(profile["postgres_dsn"], options=f"-c search_path={pg_schema}")
    with psycopg.connect(scoped) as connection:
        work = connection.execute(
            "SELECT scope_id,agent_slot_id,source_baseline FROM work_items WHERE work_item_id=%s",
            (proof["work_item_id"],),
        ).fetchall()
        message = connection.execute(
            "SELECT command_id,operation_id,state,attempts,receipt_high_water FROM delivery_messages "
            "WHERE message_id=%s", (proof["message_id"],),
        ).fetchall()
        delivery_attempts = connection.execute(
            "SELECT attempt_id,dispatch_id,status,selection_revision,selection_json->>'machine_id',"
            "selection_json->>'node_id',selection_json->>'boot_incarnation' "
            "FROM delivery_attempts WHERE message_id=%s", (proof["message_id"],),
        ).fetchall()
        registered_attempts = connection.execute(
            "SELECT attempt_id,work_item_id,runtime_id,enrollment_node_id,"
            "enrollment_node_binding_revision,enrollment_boot_incarnation,source_commit,source_tree "
            "FROM attempts WHERE attempt_id=%s", (proof["attempt_id"],),
        ).fetchall()
        node_bindings = connection.execute(
            "SELECT binding_revision,machine_id,boot_incarnation,status FROM enrolled_node_bindings "
            "WHERE node_id=%s ORDER BY binding_revision", (proof["node_id"],),
        ).fetchall()
        runtimes = connection.execute(
            "SELECT runtime_id,node_binding_revision,node_boot_incarnation,status FROM enrolled_runtimes "
            "WHERE runtime_id IN (%s,%s) ORDER BY runtime_id",
            (proof["old_runtime_id"], proof["new_runtime_id"]),
        ).fetchall()
        endpoints = connection.execute(
            "SELECT endpoint_revision,runtime_id,node_binding_revision,boot_incarnation,status,"
            "tls_certificate_sha256 FROM delivery_endpoint_registrations WHERE endpoint_id=%s "
            "ORDER BY endpoint_revision", (proof["endpoint_id"],),
        ).fetchall()
        operation = connection.execute(
            "SELECT command_id,status,provider,provider_workflow_id,provider_run_id FROM operations "
            "WHERE operation_id=%s", (proof["operation_id"],),
        ).fetchall()
        events = connection.execute(
            "SELECT event_id FROM domain_events WHERE command_id=%s", (proof["command_id"],),
        ).fetchall()
        outbox = connection.execute(
            "SELECT topic,delivered_at IS NOT NULL FROM outbox WHERE operation_id=%s",
            (proof["operation_id"],),
        ).fetchall()
        inbox = connection.execute(
            "SELECT message_id,target_agent_slot_id FROM inbox_messages WHERE message_id=%s",
            (proof["message_id"],),
        ).fetchall()
        admissions = connection.execute(
            "SELECT purpose,operation_id,attempt_id,dispatch_id,endpoint_revision,runtime_id,"
            "node_id,machine_id,admitted_boot_incarnation,journal_generation,state "
            "FROM delivery_transport_admissions WHERE operation_id=%s ORDER BY purpose",
            (proof["operation_id"],),
        ).fetchall()
        receiver_receipts = connection.execute(
            "SELECT state,operation_id,attempt_id,dispatch_id,node_binding_revision,node_id,"
            "receipt_json->>'machine_id' "
            "FROM delivery_receiver_receipts WHERE operation_id=%s ORDER BY state",
            (proof["operation_id"],),
        ).fetchall()
        projected = connection.execute(
            "SELECT layer,attempt_id,dispatch_id FROM delivery_receipts WHERE message_id=%s "
            "ORDER BY observed_at", (proof["message_id"],),
        ).fetchall()
        signed_proofs = connection.execute(
            "SELECT c.purpose_command_id,c.purpose,c.node_binding_revision,c.consumed_by,"
            "p.command_id,p.purpose FROM enrolled_node_challenges c "
            "JOIN enrolled_node_command_proofs p ON p.challenge_id=c.challenge_id "
            "WHERE p.command_id=ANY(%s) ORDER BY p.command_id",
            (proof["signed_command_ids"],),
        ).fetchall()
        command_ids = proof["mutation_command_ids"]
        mutation_counts = []
        for table in ("command_dedup", "domain_events", "operations"):
            mutation_counts.append(connection.execute(
                f"SELECT count(*) FROM {table} WHERE command_id=ANY(%s)",
                (command_ids,),
            ).fetchone()[0])
        mutation_counts.append(connection.execute(
            "SELECT count(*) FROM outbox o JOIN operations op ON op.operation_id=o.operation_id "
            "WHERE op.command_id=ANY(%s)", (command_ids,),
        ).fetchone()[0])
    expected_attempt = (
        proof["attempt_id"], proof["dispatch_id"], "delivered", 1,
        proof["machine_id"], proof["node_id"], proof["old_boot"],
    )
    expected_registration_attempt = (
        proof["attempt_id"], proof["work_item_id"], proof["old_runtime_id"],
        proof["node_id"], 1, proof["old_boot"], proof["source_commit"], proof["source_tree"],
    )
    expected_admissions = {
        ("delivery.prepare", 1, proof["old_runtime_id"], proof["old_boot"], 1),
        ("delivery.readback", 2, proof["new_runtime_id"], proof["new_boot"], 2),
        ("delivery.recover", 2, proof["new_runtime_id"], proof["new_boot"], 2),
    }
    observed_admissions = {
        (row[0], row[4], row[5], row[8], row[9]) for row in admissions
        if row[1:4] == (proof["operation_id"], proof["attempt_id"], proof["dispatch_id"])
    }
    if (
        work != [("local-scope", "local-slot", proof["source_commit"])]
        or message != [(proof["command_id"], proof["operation_id"], "delivered", 1,
                        "runtime_acknowledged")]
        or delivery_attempts != [expected_attempt]
        or registered_attempts != [expected_registration_attempt]
        or node_bindings != [
            (1, proof["machine_id"], proof["old_boot"], "retired"),
            (2, proof["machine_id"], proof["new_boot"], "active"),
        ]
        or runtimes != sorted([
            (proof["old_runtime_id"], 1, proof["old_boot"], "retired"),
            (proof["new_runtime_id"], 2, proof["new_boot"], "active"),
        ])
        or endpoints != [
            (1, proof["old_runtime_id"], 1, proof["old_boot"], "retired",
             proof["certificate_sha256"]),
            (2, proof["new_runtime_id"], 2, proof["new_boot"], "active",
             proof["certificate_sha256"]),
        ]
        or operation != [(
            proof["command_id"], "committed", "temporal",
            proof["workflow_id"], proof["run_id"],
        )]
        or len(events) != 1
        or outbox != [("message.delivery", True)]
        or inbox != [(proof["message_id"], "local-slot")]
        or len(admissions) != 3
        or observed_admissions != expected_admissions
        or any(
            (row[6], row[7]) != (proof["node_id"], proof["machine_id"])
            for row in admissions
        )
        or len(receiver_receipts) != 3
        or {(row[0], row[4]) for row in receiver_receipts} != {
            ("prepared", 1), ("readback", 2), ("runtime_acknowledged", 2),
        }
        or any(row[1:4] != (proof["operation_id"], proof["attempt_id"], proof["dispatch_id"])
               for row in receiver_receipts)
        or any(
            (row[5], row[6]) != (proof["node_id"], proof["machine_id"])
            for row in receiver_receipts
        )
        or len(projected) != 4
        or {row[0] for row in projected} != {
            "accepted_by_authority", "target_inbox_committed",
            "runtime_dispatched", "runtime_acknowledged",
        }
        or projected[0][1:] != (None, None)
        or any(row[1:] != (proof["attempt_id"], proof["dispatch_id"])
               for row in projected[1:])
        or len(signed_proofs) != len(proof["signed_command_ids"])
        or {row[0] for row in signed_proofs} != set(proof["signed_command_ids"])
        or any(
            row[0] != row[3]
            or row[0] != row[4]
            or row[1] != row[5]
            or row[2] not in {1, 2}
            for row in signed_proofs
        )
        or mutation_counts != [len(command_ids)] * 4
    ):
        raise IdentityContinuityRejected("PostgreSQL Gate identity continuity readback changed")
    return {
        "work_item_count": len(work),
        "delivery_attempt_count": len(delivery_attempts),
        "registered_attempt_count": len(registered_attempts),
        "node_binding_revisions": [row[0] for row in node_bindings],
        "endpoint_revisions": [row[0] for row in endpoints],
        "transport_admission_count": len(admissions),
        "receiver_receipt_count": len(receiver_receipts),
        "signed_registration_proof_count": len(signed_proofs),
        "inbox_projection_count": len(inbox),
        "workflow_id": operation[0][3],
        "run_id": operation[0][4],
    }


def _sqlite_readback(proof: dict[str, Any]) -> dict[str, Any]:
    logical = LogicalIdentity(
        proof["tenant_id"], proof["authority_id"], proof["authority_incarnation"],
        proof["work_item_id"], "local-scope", "local-slot", proof["machine_id"],
        proof["node_id"], proof["message_id"], proof["command_id"], proof["operation_id"],
        proof["source_commit"], proof["source_tree"], 0,
        proof["accepted_state_digest"], proof["envelope_digest"],
    )
    witness = ReceiverLedger(proof["receiver_ledger_path"])
    try:
        try:
            result = read_receiver_ledger(
                witness, logical, allowed_attempt_ids=(proof["attempt_id"],),
            )
            with witness.connect() as connection:
                meta = dict(connection.execute("SELECT key,value FROM receiver_meta"))
                rows = connection.execute(
                    "SELECT purpose,admission_json,receipt_json,state,local_dispatch_marker "
                    "FROM receiver_requests WHERE operation_id=? ORDER BY created_at,request_id",
                    (proof["operation_id"],),
                ).fetchall()
                native = connection.execute(
                    "SELECT dispatch_id,request_id FROM native_calls WHERE dispatch_id=?",
                    (proof["dispatch_id"],),
                ).fetchall()
        except ContinuityRejected as exc:
            raise IdentityContinuityRejected(str(exc)) from exc
    finally:
        witness.close()
    purposes = [row[0] for row in rows]
    admissions = [json.loads(row[1]) for row in rows]
    receipts = [json.loads(row[2])["receipt"] for row in rows]
    identity = (
        proof["message_id"], proof["command_id"], proof["operation_id"],
        proof["attempt_id"], proof["dispatch_id"], proof["machine_id"], proof["node_id"],
    )
    if (
        meta != {
            "current_boot": proof["new_boot"],
            "journal_generation": "2",
            "previous_boot": proof["old_boot"],
            "old_boot_isolation_ref": proof["old_boot_isolation_ref"],
        }
        or purposes != ["delivery.prepare", "delivery.recover", "delivery.readback"]
        or result["native_dispatch_ids"] != [proof["dispatch_id"]]
        or len(native) != 1
        or native[0][1] != proof["recovery_request_id"]
        or any((
            item["message_id"], item["command_id"], item["operation_id"],
            item["attempt_id"], item["dispatch_id"], item["machine_id"], item["node_id"],
        ) != identity for item in admissions)
        or any((
            item["message_id"], item["command_id"], item["operation_id"],
            item["attempt_id"], item["dispatch_id"], item["machine_id"], item["node_id"],
        ) != identity for item in receipts)
        or [row[3] for row in rows] != ["prepared", "runtime_acknowledged", "readback"]
        or [row[4] for row in rows] != [0, 1, 0]
    ):
        raise IdentityContinuityRejected("receiver SQLite Gate lineage changed")
    return {
        "request_count": len(rows),
        "purposes": purposes,
        "states": [row[3] for row in rows],
        "native_dispatch_count": len(native),
        "native_dispatch_id": native[0][0],
        "boot_incarnations": result["boot_incarnations"],
        "journal_generations": result["journal_generations"],
    }


def _os_readback(proof: dict[str, Any]) -> dict[str, Any]:
    pids = {
        "old_core": proof["old_core_pid"],
        "old_receiver": proof["old_receiver_pid"],
        "old_temporal_worker": proof["old_temporal_worker_pid"],
        "temporal_submitter": proof["temporal_submitter_pid"],
        "replacement_core": proof["replacement_core_pid"],
        "replacement_receiver": proof["new_receiver_pid"],
    }
    private_paths = [Path(value) for value in proof["removed_private_paths"]]
    certificate = Path(proof["certificate_evidence_path"])
    if (
        any(_pid_live(pid) for pid in pids.values())
        or len(set(pids.values())) != len(pids)
        or not _port_closed(proof["old_receiver_port"])
        or not _port_closed(proof["new_receiver_port"])
        or any(path.exists() for path in private_paths)
        or not certificate.is_file()
        or certificate.is_symlink()
        or certificate.stat(follow_symlinks=False).st_mode & 0o777 != 0o600
        or tls_fingerprint(certificate.read_bytes()) != proof["certificate_sha256"]
        or proof["tls_version"] != "TLSv1.3"
        or proof["old_boot"] == proof["new_boot"]
        or proof["old_boot_revision"] != 1
        or proof["new_boot_revision"] != 2
    ):
        raise IdentityContinuityRejected("OS process/TLS/boot/cleanup readback changed")
    return {
        "exited_pids": pids,
        "ports_closed": [proof["old_receiver_port"], proof["new_receiver_port"]],
        "tls_version": proof["tls_version"],
        "certificate_sha256": proof["certificate_sha256"],
        "boot_revisions": [1, 2],
        "private_resources_removed": True,
    }


def require_gate_qualification(value: dict[str, Any]) -> dict[str, Any]:
    """Reject component/not-run/incomplete evidence at the qualification boundary."""
    if not isinstance(value, dict):
        raise IdentityContinuityRejected("identity Gate qualification is missing")
    if value.get("status") == "component_only":
        raise IdentityContinuityRejected("component-only identity evidence cannot qualify the Gate")
    if value.get("status") != "passed" or value.get("gate_status") != "passed":
        raise IdentityContinuityRejected("identity Gate qualification did not pass")
    if value.get("missing") != []:
        raise IdentityContinuityRejected("identity Gate qualification has missing live layers")
    layers = value.get("layers")
    faults = value.get("fault_chain")
    if (
        not isinstance(layers, dict)
        or set(layers) != set(_LAYERS)
        or any(not isinstance(layers[name], dict) or not layers[name] for name in _LAYERS)
        or not isinstance(faults, dict)
        or set(faults) != {
            "ack_loss", "core_restart", "node_receiver_restart", "provider_restart",
        }
        or any(item is not True for item in faults.values())
    ):
        raise IdentityContinuityRejected("identity Gate qualification is incomplete")
    return value


def _qualification(
    layers: dict[str, dict[str, Any]], fault_chain: dict[str, bool],
) -> dict[str, Any]:
    missing = [name for name in _LAYERS if not layers.get(name)]
    missing.extend(name for name, observed in fault_chain.items() if observed is not True)
    value = {
        "status": "passed" if not missing else "not_run",
        "gate_status": "passed" if not missing else "not_run",
        "missing": missing,
        "layers": layers,
        "fault_chain": fault_chain,
    }
    return require_gate_qualification(value)


def _run_scene(
    profile: dict[str, Any],
    resources: SceneResources,
    ledger,
    *,
    pg_schema: str,
    work_id: str,
    message_id: str,
    command_id: str,
    operation_id: str,
    commit: str,
    tree: str,
    private_json,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Run all required faults before ordinary DeliveryDispatcher dispatch."""
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        require_gate_qualification(proof.get("gate_qualification"))
        return {"status": "delivered"}, proof, proof["workflow_id"], proof["run_id"]
    identity = {
        "tenant_id": resources.authority.tenant_id,
        "message_id": message_id,
        "operation_id": operation_id,
    }
    context = multiprocessing.get_context("spawn")
    if resources.old_receiver is not None:
        raise IdentityContinuityRejected("old receiver process was started more than once")
    resources.old_receiver = _start_receiver(resources.old_config, resources.authority)
    core = context.Process(target=_core_crash_child, args=(resources.service, identity))
    core.start()
    core.join(35)
    if core.is_alive():
        core.kill()
        core.join(3)
        raise IdentityContinuityRejected("old Core did not reach the post-prepare crash seam")
    if core.exitcode != 83 or _pid_live(core.pid):
        raise IdentityContinuityRejected("old Core process restart was not proven")
    with resources.authority._connect() as connection:
        attempt = connection.execute(
            "SELECT ordinal,attempt_id,dispatch_id,status,selection_json,selection_digest,"
            "invocation_json,invocation_digest FROM delivery_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchall()
        inbox_before = connection.execute(
            "SELECT count(*) FROM inbox_messages WHERE message_id=%s", (message_id,),
        ).fetchone()[0]
    if len(attempt) != 1 or attempt[0][3] != "prepared" or inbox_before != 0:
        raise IdentityContinuityRejected("old Core crash did not preserve one prepared Attempt")
    (ordinal, attempt_id, dispatch_id, _, _selection, selection_digest,
     _invocation, invocation_digest) = attempt[0]

    old_receiver_pid = _rotate_receiver(
        resources, work_id=work_id, attempt_id=attempt_id, commit=commit, tree=tree,
    )
    if resources.new_binding is None or resources.new_receiver is None or resources.new_config is None:
        raise IdentityContinuityRejected("replacement receiver was not created")
    tls = _tls_readback(resources.new_binding)
    queue = "p1-identity-" + resources.suffix
    submission_path = ledger.root / f"{SCENARIO}-provider-submission.json"
    submitter = context.Process(
        target=_submit_temporal_child,
        args=(profile, resources.service, identity, queue, str(submission_path)),
    )
    submitter.start()
    submitter.join(30)
    if submitter.is_alive():
        submitter.kill()
        submitter.join(3)
        raise IdentityContinuityRejected("Temporal submission process did not finish")
    if submitter.exitcode != 0 or _pid_live(submitter.pid) or not submission_path.is_file():
        raise IdentityContinuityRejected("Temporal submission process is incomplete")
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    workflow_id, run_id = submission.get("workflow_id"), submission.get("run_id")
    if submission.get("submitter_pid") != submitter.pid:
        raise IdentityContinuityRejected("Temporal submission process identity changed")
    if workflow_id != "acs-delivery/" + operation_id:
        raise IdentityContinuityRejected("Temporal Workflow ID is not fixed to the operation")

    result_path = ledger.root / f"{SCENARIO}-provider-result.json"
    crash_worker = context.Process(
        target=_provider_worker_child,
        args=(profile, resources.service, identity, queue, workflow_id, run_id,
              "crash", str(result_path)),
    )
    crash_worker.start()
    crash_worker.join(50)
    if crash_worker.is_alive():
        crash_worker.kill()
        crash_worker.join(3)
        raise IdentityContinuityRejected("first Temporal Worker did not crash on the bounded seam")
    if crash_worker.exitcode != 84 or _pid_live(crash_worker.pid):
        raise IdentityContinuityRejected("first Temporal Worker replacement was not proven")
    with resources.authority._connect() as connection:
        before_recovery = connection.execute(
            "SELECT status FROM delivery_attempts WHERE attempt_id=%s", (attempt_id,),
        ).fetchone()
    with sqlite3.connect(resources.receiver_ledger) as connection:
        native_before = connection.execute("SELECT count(*) FROM native_calls").fetchone()[0]
    if before_recovery != ("prepared",) or native_before != 0:
        raise IdentityContinuityRejected("first Provider Worker crossed the native boundary")

    replacement_worker = context.Process(
        target=_provider_worker_child,
        args=(profile, resources.service, identity, queue, workflow_id, run_id,
              "recover", str(result_path)),
    )
    replacement_worker.start()
    replacement_worker.join(115)
    if replacement_worker.is_alive():
        replacement_worker.kill()
        replacement_worker.join(3)
        raise IdentityContinuityRejected("replacement Temporal Worker did not finish")
    if replacement_worker.exitcode != 0 or _pid_live(replacement_worker.pid):
        raise IdentityContinuityRejected("replacement Temporal Worker exit is incomplete")
    provider_result = json.loads(result_path.read_text(encoding="utf-8"))
    if (
        provider_result.get("worker_pid") != replacement_worker.pid
        or provider_result.get("workflow_id") != workflow_id
        or provider_result.get("run_id") != run_id
        or provider_result.get("result", {}).get("status") != "delivered"
        or provider_result.get("query") != provider_result.get("result")
    ):
        raise IdentityContinuityRejected("replacement Temporal Worker result changed")

    adapter = resources.service.endpoints[resources.endpoint_id]
    with resources.authority._connect() as connection:
        pre_replay_states = connection.execute(
            "SELECT state FROM delivery_receiver_receipts WHERE operation_id=%s ORDER BY state",
            (operation_id,),
        ).fetchall()
    ack_loss_observed = pre_replay_states == [("prepared",), ("readback",)]
    recovery_request = adapter.store.dispatch_admission(operation_id)
    if recovery_request is None or recovery_request.admission.purpose != "delivery.recover":
        raise IdentityContinuityRejected("replacement recovery admission is missing")
    recovery_replay = adapter.transport.send(recovery_request)
    adapter.store.persist_receipt(recovery_replay)
    signed = _signed_exchange_rows(resources.authority, operation_id, resources.receiver_ledger)
    if recovery_replay != signed["delivery.recover"][1]:
        raise IdentityContinuityRejected("exact signed recovery replay changed")
    temporal = _temporal_readback(profile, workflow_id, run_id, identity, queue)

    with resources.authority._connect() as connection:
        message = connection.execute(
            "SELECT accepted_state_digest,envelope_hash FROM delivery_messages WHERE message_id=%s",
            (message_id,),
        ).fetchone()
    accepted_state_digest, envelope_digest = message
    logical = LogicalIdentity(
        resources.authority.tenant_id,
        resources.authority.context.authority_id,
        resources.authority.context.authority_incarnation,
        work_id,
        "local-scope",
        "local-slot",
        resources.old_binding.registration.machine_id,
        resources.old_binding.registration.node_id,
        message_id,
        command_id,
        operation_id,
        commit,
        tree,
        0,
        accepted_state_digest,
        envelope_digest,
    )
    attempt_readback = AttemptReadback(
        ordinal,
        logical.tenant_id,
        attempt_id,
        dispatch_id,
        message_id,
        command_id,
        operation_id,
        work_id,
        logical.scope_id,
        logical.agent_slot_id,
        logical.machine_id,
        logical.node_id,
        logical.authority_id,
        logical.authority_incarnation,
        commit,
        tree,
        resources.endpoint_id,
        1,
        resources.old_runtime_id,
        1,
        1,
        resources.old_boot,
        "delivered",
    )
    audit = audit_component_chain(
        logical,
        (
            (attempt_readback, resources.old_binding, *signed["delivery.prepare"]),
            (attempt_readback, resources.new_binding, *signed["delivery.recover"]),
        ),
        (
            NodeBootReadback(1, resources.old_boot, logical.machine_id, logical.node_id),
            NodeBootReadback(2, resources.new_boot, logical.machine_id, logical.node_id),
        ),
        authority_public_key=public_key(resources.authority_key),
        inbox_projection_ids=(message_id,),
        driver_dispatch_ids=(dispatch_id,),
        temporal_workflow_id=workflow_id,
    )
    if (
        audit.get("status") != "component_only"
        or audit.get("gate_status") != "not_run"
        or audit.get("missing") != [
            "postgresql_live", "sqlite_live", "temporal_live", "os_restart_live",
        ]
    ):
        raise IdentityContinuityRejected("component audit semantics changed")

    new_receiver_pid = resources.new_receiver.pid
    _stop_owned(resources.new_receiver, "replacement receiver")
    for path in (resources.node_seed, resources.cert_path, resources.tls_key_path):
        path.unlink()
    proof: dict[str, Any] = {
        "tenant_id": resources.authority.tenant_id,
        "authority_id": resources.authority.context.authority_id,
        "authority_incarnation": resources.authority.context.authority_incarnation,
        "work_item_id": work_id,
        "message_id": message_id,
        "command_id": command_id,
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "dispatch_id": dispatch_id,
        "source_commit": commit,
        "source_tree": tree,
        "machine_id": logical.machine_id,
        "node_id": logical.node_id,
        "endpoint_id": resources.endpoint_id,
        "old_runtime_id": resources.old_runtime_id,
        "new_runtime_id": resources.new_runtime_id,
        "old_boot": resources.old_boot,
        "new_boot": resources.new_boot,
        "old_boot_revision": 1,
        "new_boot_revision": 2,
        "old_boot_isolation_ref": resources.new_config.old_boot_isolation_ref,
        "old_core_pid": core.pid,
        "replacement_core_pid": replacement_worker.pid,
        "old_receiver_pid": old_receiver_pid,
        "new_receiver_pid": new_receiver_pid,
        "old_temporal_worker_pid": crash_worker.pid,
        "temporal_submitter_pid": submitter.pid,
        "old_receiver_port": resources.old_binding.locator_port,
        "new_receiver_port": resources.new_binding.locator_port,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "queue": queue,
        "provider_result_sha256": _hash(result_path.read_bytes()),
        "accepted_state_digest": accepted_state_digest,
        "envelope_digest": envelope_digest,
        "selection_digest": selection_digest,
        "invocation_digest": invocation_digest,
        "recovery_request_id": recovery_request.admission.request_id,
        "ack_loss_observed": ack_loss_observed,
        "exact_recovery_replay": True,
        "tls_version": tls["version"],
        "certificate_sha256": tls["certificate_sha256"],
        "certificate_evidence_path": str(resources.cert_der_path),
        "receiver_ledger_path": str(resources.receiver_ledger),
        "removed_private_paths": [
            str(resources.node_seed), str(resources.cert_path), str(resources.tls_key_path),
        ],
        "mutation_command_ids": resources.mutation_command_ids,
        "signed_command_ids": resources.signed_command_ids,
        "component_audit": audit,
        "temporal_submission_readback": temporal,
    }
    if not ack_loss_observed:
        raise IdentityContinuityRejected("replacement receiver ACK loss was not observed")
    layers = {
        "postgresql": _pg_readback(profile, pg_schema, proof),
        "sqlite": _sqlite_readback(proof),
        "temporal": _temporal_readback(profile, workflow_id, run_id, identity, queue),
        "os": _os_readback(proof),
    }
    proof["gate_qualification"] = _qualification(layers, {
        "ack_loss": ack_loss_observed,
        "core_restart": core.exitcode == 83 and core.pid != replacement_worker.pid,
        "node_receiver_restart": (
            old_receiver_pid != new_receiver_pid
            and resources.old_boot != resources.new_boot
        ),
        "provider_restart": (
            crash_worker.exitcode == 84 and crash_worker.pid != replacement_worker.pid
        ),
    })
    private_json(proof_path, proof)
    return {"status": "delivered"}, proof, workflow_id, run_id


def cleanup_owned(resources: SceneResources | None) -> None:
    """Stop only scene-owned children and remove scene-owned private key material."""
    if resources is None:
        return
    _stop_owned(resources.old_receiver, "old receiver")
    _stop_owned(resources.new_receiver, "replacement receiver")
    for path in (resources.node_seed, resources.cert_path, resources.tls_key_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def run(*args, **kwargs):
    resources = args[1] if len(args) > 1 else kwargs.get("resources")
    try:
        return _run_scene(*args, **kwargs)
    except ContinuityRejected as exc:
        cleanup_owned(resources)
        raise IdentityContinuityRejected(str(exc)) from exc
    except BaseException:
        cleanup_owned(resources)
        raise


def read_layer(profile, kind, ledger, row, lineage):
    proof = lineage.get("identity_continuity_proof")
    path = ledger.root / f"{SCENARIO}-proof.json"
    if (
        not isinstance(proof, dict)
        or not path.is_file()
        or json.loads(path.read_text(encoding="utf-8")) != proof
        or any(proof.get(key) != lineage[key] for key in (
            "message_id", "command_id", "operation_id", "attempt_id", "dispatch_id",
            "machine_id", "node_id",
        ))
        or proof.get("source_commit") != row["source_commit"]
        or proof.get("source_tree") != row["source_tree"]
    ):
        raise IdentityContinuityRejected("identity continuity proof left the Runtime lineage")
    qualification = require_gate_qualification(proof.get("gate_qualification"))
    if kind in {"command_output", "driver"}:
        raw = ledger.root / row["raw_path"]
        try:
            raw_value = json.loads(raw.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise IdentityContinuityRejected("identity raw scenario evidence is unavailable") from None
        if (
            _hash(raw.read_bytes()) != row["test_digest"]
            or raw_value.get("lineage") != lineage
        ):
            raise IdentityContinuityRejected("identity raw scenario evidence changed")
    identity = {
        "tenant_id": proof["tenant_id"],
        "message_id": proof["message_id"],
        "operation_id": proof["operation_id"],
    }
    if kind == "postgresql":
        observed = _pg_readback(profile, row["pg_schema"], proof)
        label = "identity_pg_readback"
    elif kind == "sqlite":
        observed = _sqlite_readback(proof)
        label = "identity_receiver_sqlite_readback"
    elif kind == "temporal":
        observed = _temporal_readback(
            profile, proof["workflow_id"], proof["run_id"], identity, proof["queue"],
        )
        label = "identity_temporal_readback"
    elif kind == "os":
        observed = _os_readback(proof)
        label = "identity_os_readback"
    elif kind == "driver":
        observed = _sqlite_readback(proof)
        if observed["native_dispatch_count"] != 1:
            raise IdentityContinuityRejected("identity native dispatch count changed")
        return {
            "identity_single_native_dispatch": True,
            "identity_signed_receipt_replay": proof["exact_recovery_replay"],
            "gate_qualification": "passed",
        }
    else:
        if proof["component_audit"].get("status") != "component_only":
            raise IdentityContinuityRejected("component audit boundary changed")
        return {
            "identity_fault_chain": qualification["fault_chain"],
            "identity_component_audit_status": "component_only",
            "gate_qualification": "passed",
        }
    if observed != qualification["layers"][kind]:
        raise IdentityContinuityRejected(f"{kind} qualification readback changed")
    return {label: True, "gate_qualification": "passed", **observed}

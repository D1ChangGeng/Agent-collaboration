"""Formal P1 identity continuity scene bound to one Domain delivery lineage."""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import socket
import sqlite3
from dataclasses import replace
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

from runtime.receiver_config import ConnectionTarget, EndpointBootstrap, NodeIdentity, ReceiverRuntimeConfig
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign, tls_fingerprint
from runtime.receiver_models import EndpointRegistration, PrepareBody, ReadbackBody, RecoveryBody
from runtime.remote_endpoint import RemoteNodeTransport, serve
from runtime.sender import AdmissionFactory, DeliveryIdentity
from tools.runtime.p1_identity_continuity_probe import (
    AttemptReadback, LogicalIdentity, NodeBootReadback, audit_component_chain,
    read_receiver_ledger,
)

SCENARIO = "P1-IDENTITY-CONTINUITY"


class IdentityContinuityRejected(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _free_port() -> int:
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


def _authority_current(_admission) -> bool:
    return True


def _native_invoke(admission) -> dict[str, str]:
    return {"native_ack_ref": "identity-continuity:" + admission.dispatch_id}


def _certificate(root: Path) -> tuple[Path, Path, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acs-p1-receiver")])
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=15))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = root / "receiver-cert.pem", root / "receiver-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_path.chmod(0o600); key_path.chmod(0o600)
    return cert_path, key_path, tls_fingerprint(cert.public_bytes(serialization.Encoding.DER))


def _start(config: ReceiverRuntimeConfig):
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=serve, args=(config, ready, _authority_current, _native_invoke),
    )
    process.start()
    if not ready.wait(8) or not process.is_alive():
        process.join(2)
        raise IdentityContinuityRejected("signed TLS receiver did not become ready")
    return process


def _stop(process) -> None:
    process.terminate(); process.join(8)
    if process.is_alive():
        process.kill(); process.join(3)
    if process.is_alive():
        raise IdentityContinuityRejected("signed TLS receiver process remains live")


def run(
    authority, node, ledger, work_id: str, message_id: str, operation_id: str,
    commit: str, tree: str, suffix: str, private_json,
) -> dict[str, Any]:
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    if proof_path.exists():
        return json.loads(proof_path.read_text(encoding="utf-8"))
    with authority._connect() as connection:
        attempt = connection.execute(
            "SELECT ordinal,attempt_id,dispatch_id,status,selection_revision,selection_json,"
            "selection_digest,invocation_json,invocation_digest "
            "FROM delivery_attempts WHERE message_id=%s ORDER BY ordinal", (message_id,),
        ).fetchall()
        work = connection.execute(
            "SELECT scope_id,agent_slot_id,source_baseline FROM work_items WHERE work_item_id=%s",
            (work_id,),
        ).fetchone()
        message = connection.execute(
            "SELECT command_id,accepted_state_digest,envelope_json,envelope_hash "
            "FROM delivery_messages WHERE message_id=%s", (message_id,),
        ).fetchone()
    if len(attempt) != 1 or attempt[0][3] != "delivered" or work != (
        "local-scope", "local-slot", commit,
    ):
        raise IdentityContinuityRejected("identity scene requires one delivered Domain Attempt")
    (ordinal, attempt_id, dispatch_id, status, selection_revision, selection,
     selection_digest, invocation, invocation_digest) = attempt[0]
    command_id, accepted_state_digest, envelope, envelope_digest = message
    if (
        not isinstance(envelope, dict) or not isinstance(selection, dict)
        or not isinstance(invocation, dict)
        or sha256(envelope) != envelope_digest
        or sha256(selection) != selection_digest
        or sha256(invocation) != invocation_digest
    ):
        raise IdentityContinuityRejected("Domain delivery canonical digests changed")
    receiver_selection = dict(selection)
    receiver_invocation = dict(invocation)
    root = ledger.root / f"{SCENARIO}-receiver"
    root.mkdir(mode=0o700)
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    node_seed = root / "node-signing.seed"
    node_seed.write_text(node_key.encode().hex(), encoding="ascii"); node_seed.chmod(0o600)
    cert_path, tls_key_path, cert_sha = _certificate(root)
    receiver_ledger = root / "receiver.sqlite"
    deadline = datetime.now(UTC) + timedelta(minutes=3)
    logical = LogicalIdentity(
        authority.tenant_id, authority.context.authority_id,
        authority.context.authority_incarnation, work_id, "local-scope", "local-slot",
        node.machine_id, node.node_id, message_id, command_id, operation_id, commit, tree, 0,
        accepted_state_digest, envelope_digest,
    )
    identity = DeliveryIdentity(
        message_id, command_id, operation_id, attempt_id, dispatch_id, 0,
        logical.accepted_state_digest, logical.envelope_digest,
        selection_digest, invocation_digest, deadline,
    )
    cert_config_sha = hashlib.sha256((commit + tree).encode()).hexdigest()

    def configuration(binding, boot: str, generation: int, isolation: str | None):
        return ReceiverRuntimeConfig(
            binding=binding, authority_key_id="authority-key-1", authority_key_revision=1,
            authority_public_key=public_key(authority_key),
            authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
            tls_cert_path=str(cert_path), tls_key_path=str(tls_key_path),
            node_signing_key_path=str(node_seed), ledger_path=str(receiver_ledger),
            expected_boot_incarnation=boot, journal_generation=generation,
            old_boot_isolation_ref=isolation,
        )

    def binding(revision: int, boot: str, port: int):
        identity_node = NodeIdentity(
            logical.tenant_id, logical.authority_id, logical.authority_incarnation,
            logical.node_id, revision, "identity-runtime", 1, logical.machine_id,
            boot, logical.scope_id, logical.agent_slot_id, "node-key-1", public_key(node_key),
        )
        registration = EndpointRegistration(
            registration_id=f"identity-registration-{revision}",
            endpoint_id=selection["endpoint_id"],
            endpoint_revision=revision, connection_ref="identity-loopback",
            tenant_id=logical.tenant_id, authority_id=logical.authority_id,
            authority_incarnation=logical.authority_incarnation, node_id=logical.node_id,
            node_binding_revision=revision, runtime_id="identity-runtime", runtime_revision=1,
            machine_id=logical.machine_id, boot_incarnation=boot,
            scope_id=logical.scope_id, agent_slot_id=logical.agent_slot_id,
            tls_certificate_sha256=cert_sha, config_sha256=cert_config_sha,
            expires_at=deadline,
        )
        return EndpointBootstrap(
            {"identity-loopback": ConnectionTarget("identity-loopback", "127.0.0.1", port, "loopback")},
            identity_node,
        ).register(registration, sign(node_key, registration))

    old_binding = binding(1, "identity-boot-1", _free_port())
    old_config = configuration(old_binding, "identity-boot-1", 1, None)
    old_factory = AdmissionFactory(old_config, authority_key, identity)
    prepare_body = PrepareBody(
        envelope=envelope, invocation=receiver_invocation, selection=receiver_selection,
    )
    old_process = _start(old_config)
    try:
        prepare = old_factory.request("delivery.prepare", prepare_body)
        prepared = RemoteNodeTransport(old_config).send(prepare)
    finally:
        _stop(old_process)

    new_binding = binding(2, "identity-boot-2", _free_port())
    new_config = configuration(new_binding, "identity-boot-2", 2, "old-boot-process-stopped")
    new_factory = AdmissionFactory(new_config, authority_key, identity)
    recovery_body = RecoveryBody(
        prepare_request_id=prepare.admission.request_id,
        marker_receipt_id="postgres-runtime-dispatched",
        old_boot_incarnation="identity-boot-1", new_boot_incarnation="identity-boot-2",
        journal_generation=2, old_boot_isolation_ref="old-boot-process-stopped",
        old_endpoint_revision=1, new_endpoint_revision=2,
        old_runtime_revision=1, new_runtime_revision=1,
    )
    recovered_request = new_factory.request(
        "delivery.recover", recovery_body, boot_incarnation="identity-boot-2", journal_generation=2,
    )
    new_process = _start(new_config)
    try:
        transport = RemoteNodeTransport(new_config)
        recovered = transport.send(recovered_request)
        replay = transport.send(recovered_request)
        readback_request = new_factory.request(
            "delivery.readback", ReadbackBody(operation_id=operation_id, dispatch_id=dispatch_id),
            boot_incarnation="identity-boot-2", journal_generation=2,
        )
        readback = transport.send(readback_request)
        with socket.create_connection((new_binding.locator_host, new_binding.locator_port)) as raw:
            with RemoteNodeTransport._context().wrap_socket(raw, server_hostname="localhost") as tls:
                tls_version = tls.version()
    finally:
        _stop(new_process)
    attempt_readback = AttemptReadback(
        ordinal, logical.tenant_id, attempt_id, dispatch_id, message_id, command_id,
        operation_id, work_id, logical.scope_id, logical.agent_slot_id,
        logical.machine_id, logical.node_id, logical.authority_id,
        logical.authority_incarnation, commit, tree, selection["endpoint_id"], 1,
        "identity-runtime", 1, 1, "identity-boot-1", status,
    )
    audit = audit_component_chain(
        logical,
        ((attempt_readback, old_binding, prepare, prepared),
         (attempt_readback, new_binding, recovered_request, recovered)),
        (NodeBootReadback(1, "identity-boot-1", logical.machine_id, logical.node_id),
         NodeBootReadback(2, "identity-boot-2", logical.machine_id, logical.node_id)),
        authority_public_key=public_key(authority_key),
        inbox_projection_ids=(message_id,), driver_dispatch_ids=(dispatch_id,),
        temporal_workflow_id="acs-delivery/" + operation_id,
    )
    from runtime.receiver import ReceiverLedger
    ledger_readback = read_receiver_ledger(
        ReceiverLedger(new_config.ledger_path), logical, allowed_attempt_ids=(attempt_id,),
    )
    for path in (node_seed, cert_path, tls_key_path):
        path.unlink()
    proof = {
        "work_item_id": work_id, "message_id": message_id, "command_id": command_id,
        "operation_id": operation_id, "attempt_id": attempt_id, "dispatch_id": dispatch_id,
        "source_commit": commit, "source_tree": tree, "machine_id": logical.machine_id,
        "node_id": logical.node_id, "old_pid": old_process.pid, "new_pid": new_process.pid,
        "old_process_exited": not old_process.is_alive(), "new_process_exited": not new_process.is_alive(),
        "tls_version": tls_version, "certificate_sha256": cert_sha,
        "prepare_state": prepared.receipt.state, "recovery_state": recovered.receipt.state,
        "readback_state": readback.receipt.state, "exact_recovery_replay": replay == recovered,
        "signed_receipt_sha256": hashlib.sha256(recovered.model_dump_json().encode()).hexdigest(),
        "audit": audit, "ledger": ledger_readback,
        "private_key_files_removed": all(not path.exists() for path in (node_seed, cert_path, tls_key_path)),
    }
    if (
        tls_version != "TLSv1.3" or proof["prepare_state"] != "prepared"
        or proof["recovery_state"] != "runtime_acknowledged"
        or proof["readback_state"] != "readback" or not proof["exact_recovery_replay"]
        or ledger_readback["native_dispatch_ids"] != [dispatch_id]
        or audit["boot_revisions"] != [1, 2]
    ):
        raise IdentityContinuityRejected("identity continuity evidence is incomplete")
    private_json(proof_path, proof)
    return proof


def read_layer(profile, kind, ledger, row, lineage):
    proof = lineage.get("identity_continuity_proof")
    path = ledger.root / f"{SCENARIO}-proof.json"
    if not isinstance(proof, dict) or json.loads(path.read_text()) != proof:
        raise IdentityContinuityRejected("identity continuity proof changed")
    if any(proof.get(key) != lineage[key] for key in (
        "message_id", "command_id", "operation_id", "attempt_id", "dispatch_id",
        "machine_id", "node_id",
    )) or proof.get("source_commit") != row["source_commit"] or proof.get("source_tree") != row["source_tree"]:
        raise IdentityContinuityRejected("identity continuity left the Runtime lineage")
    if kind == "postgresql":
        scoped = make_conninfo(profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            attempt = connection.execute(
                "SELECT attempt_id,dispatch_id,status,selection_json->>'machine_id',selection_json->>'node_id' "
                "FROM delivery_attempts WHERE message_id=%s", (proof["message_id"],),
            ).fetchone()
        if attempt != (proof["attempt_id"], proof["dispatch_id"], "delivered",
                       proof["machine_id"], proof["node_id"]):
            raise IdentityContinuityRejected("PG identity continuity lineage changed")
        return {"identity_pg_readback": True}
    if kind == "sqlite":
        if proof["ledger"]["native_dispatch_ids"] != [proof["dispatch_id"]]:
            raise IdentityContinuityRejected("receiver SQLite duplicated the native effect")
        return {"identity_receiver_ledger_readback": True}
    if kind == "temporal":
        return {"identity_temporal_operation_bound": True}
    if kind == "driver":
        return {"identity_single_native_dispatch": True, "identity_signed_receipt": True}
    if kind == "os":
        if not proof["old_process_exited"] or not proof["new_process_exited"] or not proof["private_key_files_removed"]:
            raise IdentityContinuityRejected("identity receiver OS cleanup changed")
        return {"identity_tls13": True, "identity_boot_replacement": True}
    return {"identity_signed_exchange": True, "identity_exact_replay": True}

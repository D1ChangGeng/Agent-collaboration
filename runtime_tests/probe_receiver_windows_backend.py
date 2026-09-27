"""Local Windows ACL, SQLite, TLS and no-model Receiver backend probe."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.signing import SigningKey

from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import public_key, sign, tls_fingerprint
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.remote_endpoint import serve


def private_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    user = subprocess.run(
        ["whoami.exe"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["icacls.exe", str(path), "/inheritance:r"], check=True, capture_output=True)
    subprocess.run(
        ["icacls.exe", str(path), "/grant:r", f"{user}:(OI)(CI)F", "/T", "/C"],
        check=True, capture_output=True,
    )


def free_port() -> int:
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


def certificate(root: Path):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "receiver")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(minutes=10))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = root / "cert.pem", root / "tls-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return cert_path, key_path, tls_fingerprint(cert.public_bytes(serialization.Encoding.DER))


def main() -> int:
    root = Path(os.environ["ACS_WINDOWS_RECEIVER_PROBE_ROOT"]).resolve()
    private_root(root)
    authority, node = SigningKey.generate(), SigningKey.generate()
    cert, tls_key, cert_sha = certificate(root)
    node_seed = root / "node.seed"
    node_seed.write_text(node.encode().hex())
    registration = EndpointRegistration(
        registration_id="windows-probe-registration", endpoint_id="windows-probe-endpoint",
        endpoint_revision=1, connection_ref="windows-loopback", tenant_id="tenant",
        authority_id="authority", authority_incarnation="incarnation", node_id="windows-node",
        node_binding_revision=1, runtime_id="windows-runtime", runtime_revision=1,
        machine_id="windows-machine", boot_incarnation="windows-boot", scope_id="scope",
        agent_slot_id="slot", tls_certificate_sha256=cert_sha, config_sha256="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    binding = EndpointBinding(
        registration=registration, locator_host="127.0.0.1", locator_port=free_port(),
        route_class="loopback", node_key_id="windows-node-key",
        node_public_key=public_key(node), registration_signature=sign(node, registration),
    )
    config = ReceiverRuntimeConfig(
        binding=binding, authority_key_id="authority-key", authority_key_revision=1,
        authority_public_key=public_key(authority),
        authority_public_key_fingerprint=hashlib.sha256(bytes.fromhex(public_key(authority))).hexdigest(),
        tls_cert_path=str(cert), tls_key_path=str(tls_key),
        node_signing_key_path=str(node_seed), ledger_path=str(root / "receiver.sqlite"),
        expected_boot_incarnation="windows-boot", journal_generation=1,
    )
    # ACL each created file before admission.
    private_root(root / "private-child")
    user = subprocess.run(["whoami.exe"], capture_output=True, text=True, check=True).stdout.strip()
    for path in (cert, tls_key, node_seed):
        subprocess.run(["icacls.exe", str(path), "/inheritance:r"], check=True, capture_output=True)
        subprocess.run(["icacls.exe", str(path), "/grant:r", f"{user}:F"], check=True, capture_output=True)
    errors = []

    def run():
        try:
            serve(
                config, authorize_current=lambda _admission: True,
                native_invoke=lambda admission: {
                    "native_ack_ref": "windows-no-model:" + admission.dispatch_id,
                    "model_invoked": False,
                },
            )
        except BaseException as error:
            errors.append(type(error).__name__ + ":" + str(error))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", binding.locator_port), timeout=0.2):
                break
        except OSError:
            if errors:
                raise RuntimeError(errors[0])
            time.sleep(0.05)
    else:
        raise RuntimeError("Windows receiver listener did not start")
    print(json.dumps({
        "status": "passed", "listener": True,
        "ledger_created": (root / "receiver.sqlite").is_file(),
        "backend": "windows-acl-handle-identity",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

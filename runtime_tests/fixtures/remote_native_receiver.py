"""Opt-in cross-machine controller; messages enter only the production Receiver.

stdin carries private, test-only bootstrap material. stdout contains public
bindings and observations, never credentials. The model's only communication
channel is its independently authenticated ACS MCP instance.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.signing import SigningKey

from runtime.communication_tools import DESCRIPTIONS, adopt_catalog
from runtime.opencode_http import listener_owner_pids
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import public_key, sign, tls_fingerprint
from runtime.receiver_deployment import bind_process_config, dump_process_config, inspect_factory
from runtime.receiver_entry import load_callbacks, load_process_config
from runtime.receiver_models import EndpointBinding
from runtime.remote_endpoint import ReceiverHTTPServer


def emit(value):
    print(json.dumps(value), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        raise EOFError("test controller disconnected")
    return json.loads(line)


def write_private(path, data):
    path.write_text(data, encoding="utf-8")
    path.chmod(0o600)


def contract_view(catalog):
    return {
        name: {
            key: catalog["tools"][name][key]
            for key in ("description", "input_schema", "security_scopes")
        }
        for name in DESCRIPTIONS
    }


def read_mcp_status(capacity):
    """External test oracle; the production Driver's route allowlist stays intact."""
    client = capacity.driver.client
    capacity._current(capacity._lifecycle_operation("spawn"), capacity.binding)
    assert client.verify_owner(), "test Native listener ownership changed"
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=60)
    try:
        connection.connect()
        assert client.verify_owner(), "test Native listener ownership changed before authentication"
        connection.request(
            "GET",
            "/mcp?" + urlencode({"directory": client.directory}),
            headers={"Authorization": client._authorization, "Accept": "application/json"},
        )
        response = connection.getresponse()
        body = response.read(65537)
        assert response.status == 200 and len(body) <= 65536, "test MCP status readback unavailable"
        return json.loads(body)
    finally:
        connection.close()


def ownership_snapshot(capacity):
    proof = capacity.supervisor.inspect(capacity.driver.owned)
    owners = sorted(listener_owner_pids(capacity.driver.client.port))
    processes = []
    for pid in set(owners) | set(proof.get("remaining_pids", [])):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            processes.append(
                {
                    "pid": pid,
                    "ppid": int(fields[1]),
                    "pgrp": int(fields[2]),
                    "session": int(fields[3]),
                    "executable": Path(os.readlink(f"/proc/{pid}/exe")).name,
                }
            )
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            processes.append({"pid": pid, "gone": True})
    return {"process_proof": proof, "listener_owners": owners, "processes": processes}


def main():
    os.umask(0o077)
    state = ROOT / "state"
    state.mkdir(mode=0o700)
    node_key = SigningKey.generate()
    write_private(state / "node.seed", node_key.encode().hex())
    tls_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acs-isolated-receiver")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .sign(tls_key, hashes.SHA256())
    )
    (state / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (state / "tls.pem").write_bytes(
        tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        listen_port = reservation.getsockname()[1]
    # Read the already-present public contract on this host, then apply the
    # current source's adoption function. No local configuration is copied.
    catalog = adopt_catalog(json.loads(Path(os.environ["ACS_REMOTE_BASE_CATALOG"]).read_text()))
    write_private(state / "catalog.json", json.dumps(catalog))
    source = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in (ROOT / "runtime", ROOT / "runtime_deployment", ROOT / "runtime_tests")
        for path in folder.rglob("*")
        if path.suffix in {".py", ".sql"}
    }
    emit(
        {
            "state": "prepared",
            "node_public_key": public_key(node_key),
            "listen_port": listen_port,
            "certificate_sha256": tls_fingerprint(cert.public_bytes(serialization.Encoding.DER)),
            "source_files": source,
            "contract": contract_view(catalog),
            "hostname": socket.gethostname(),
        }
    )
    callbacks = server = worker = None
    try:
        while True:
            request = receive()
            action = request["action"]
            if action == "sign":
                emit(
                    {
                        "signature": node_key.sign(
                            bytes.fromhex(request["message_hex"])
                        ).signature.hex()
                    }
                )
            elif action == "configure":
                for key in tuple(os.environ):
                    if key.startswith(("OPENCODE_", "XDG_", "ACS_RECEIVER_")):
                        del os.environ[key]
                home, work = state / "home", state / "work"
                home.mkdir(mode=0o700)
                work.mkdir(mode=0o700)
                os.environ.update(
                    HOME=str(home),
                    ACS_RECEIVER_DSN=request["dsn"],
                    ACS_B_DSN=request["dsn"],
                    ACS_B_CREDENTIAL=request["credential"],
                )
                surface = state / "surface.json"
                write_private(
                    surface,
                    json.dumps(
                        {
                            "access_mode": "owner",
                            "context": request["context"],
                            "delivery_maintenance": "external",
                            "dsn_ref": {"kind": "environment", "name": "ACS_B_DSN"},
                            "credential_ref": {"kind": "environment", "name": "ACS_B_CREDENTIAL"},
                        }
                    ),
                )
                # A wrapper named mcp.py shadows the installed MCP SDK when
                # Python prepends the script's directory to its import path.
                wrapper = state / "acs_b_stdio.py"
                write_private(
                    wrapper,
                    "import sys\nsys.path.insert(0,"
                    + repr(str(ROOT))
                    + ")\n"
                    + "sys.stderr=open("
                    + repr(str(state / "mcp.stderr.txt"))
                    + ",'a',buffering=1)\n"
                    + "from runtime.project_entry import main\nraise SystemExit(main("
                    + repr(
                        [
                            "--config",
                            str(surface),
                            "--catalog",
                            str(state / "catalog.json"),
                            "--profile",
                            "engineer",
                        ]
                    )
                    + "))\n",
                )
                native = {"mcp": {}, "plugin": [], "permission": {"*": "deny"}}
                if request.get("provider_key"):
                    os.environ["ACS_B_PROVIDER_KEY"] = request["provider_key"]
                    native.update(
                        model="acs-test/gpt-6.1-sol",
                        default_agent="acs-peer",
                        provider={
                            "acs-test": {
                                "npm": "@ai-sdk/openai-compatible",
                                "name": "Isolated approved Provider",
                                "options": {
                                    "baseURL": "https://api.payapionline.top/v1",
                                    "apiKey": "{env:ACS_B_PROVIDER_KEY}",
                                },
                                "models": {"gpt-6.1-sol": {"name": "gpt-6.1-sol"}},
                            }
                        },
                        agent={
                            "acs-peer": {
                                "mode": "primary",
                                "prompt": "You are ordinary Agent B, collaborator slot-b in ACS project-alpha. "
                                f"The release label for this isolated exercise is {request['label']}. "
                                "Assist contacts through ACS using the received reply relationship. Use only ACS MCP tools.",
                                "permission": {"*": "deny", "acs_*": "allow"},
                            }
                        },
                        mcp={
                            "acs": {
                                "type": "local",
                                "command": [sys.executable, str(wrapper)],
                                "enabled": True,
                                "timeout": 180000,
                            }
                        },
                        permission={"*": "deny", "acs_*": "allow"},
                    )
                os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(native)
                binding = EndpointBinding.model_validate_json(
                    json.dumps(request["binding"]), strict=True
                )
                binding = binding.model_copy(
                    update={"registration_signature": sign(node_key, binding.registration)}
                )
                config = ReceiverRuntimeConfig(
                    binding=binding,
                    **request["client_config"],
                    tls_cert_path=str(state / "cert.pem"),
                    tls_key_path=str(state / "tls.pem"),
                    node_signing_key_path=str(state / "node.seed"),
                    ledger_path=str(state / "receiver.sqlite"),
                    listen_host="127.0.0.1",
                    listen_port=listen_port,
                )
                settings = {
                    "schema_version": "acs-receiver-opencode-factory/1",
                    "binding_id": "remote-opencode",
                    "capacity_attempt_id": "remote-opencode-capacity",
                    "executable": request["binary"],
                    "cwd": str(work),
                    "home": str(home),
                    "temp_root": str(state / "temp"),
                    "driver_journal": str(state / "driver.sqlite"),
                    "node_journal": str(state / "node.sqlite"),
                    "runtime_id": binding.registration.runtime_id,
                }
                factory, _, _, _ = inspect_factory(
                    "runtime_deployment.receiver_opencode:callbacks", settings=settings
                )
                process = bind_process_config(config, factory, node_key)
                write_private(state / "process.json", dump_process_config(process))
                emit(
                    {
                        "state": "configured",
                        "registration": process.runtime.binding.registration.model_dump(
                            mode="json"
                        ),
                        "registration_signature": process.runtime.binding.registration_signature,
                    }
                )
            elif action == "start":
                started_at = time.monotonic()
                process = load_process_config(state / "process.json")
                callbacks = load_callbacks(process)
                capacity = callbacks.native_invoke.__self__
                mcp_status = {}
                if os.environ.get("ACS_B_PROVIDER_KEY"):
                    mcp_status = read_mcp_status(capacity)
                    safe_status = json.dumps(mcp_status)
                    for variable in ("ACS_B_PROVIDER_KEY", "ACS_B_CREDENTIAL"):
                        if os.environ.get(variable):
                            safe_status = safe_status.replace(os.environ[variable], "[redacted]")
                    mcp_status = json.loads(safe_status)
                    write_private(state / "mcp-status.json", safe_status)
                server = ReceiverHTTPServer(
                    process.runtime,
                    node_key,
                    callbacks.authorize_current,
                    callbacks.native_invoke,
                    callbacks.close,
                    callbacks.readiness,
                    clock=callbacks.clock,
                )
                worker = threading.Thread(
                    target=server.serve_forever, kwargs={"poll_interval": 0.05}
                )
                worker.start()
                server.verify_presented_certificate()
                emit(
                    {
                        "state": "started",
                        "native": callbacks.native_invoke.__self__.health(),
                        "mcp": mcp_status,
                        "startup_seconds": time.monotonic() - started_at,
                    }
                )
            elif action == "observe":
                capacity = callbacks.native_invoke.__self__
                read_at = time.monotonic()
                native = capacity.health()
                health_seconds = time.monotonic() - read_at
                with capacity.journal._connect() as connection:
                    events = [
                        json.loads(row[0])
                        for row in connection.execute(
                            "SELECT body FROM driver_events WHERE kind='http_dispatch'"
                        )
                    ]
                with sqlite3.connect(state / "receiver.sqlite") as connection:
                    requests = connection.execute(
                        "SELECT purpose,count(*) FROM receiver_requests GROUP BY purpose"
                    ).fetchall()
                emit(
                    {
                        "state": "observed",
                        "native": native,
                        "health_seconds": health_seconds,
                        "requests": requests,
                        "driver_requests": events,
                        "collector": hasattr(capacity, "collector"),
                        "event_subscription": capacity.driver._event_thread is not None,
                    }
                )
            elif action == "stop":
                break
            else:
                raise ValueError("unknown test controller action")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            worker.join(timeout=10)
        if callbacks is not None:
            capacity = callbacks.native_invoke.__self__
            owned = capacity.driver.owned
            ownership = ownership_snapshot(capacity) if owned is not None else None
            write_private(state / "ownership-before-stop.json", json.dumps(ownership))
            callbacks.close()
            stopped = (
                capacity.supervisor.inspect(owned)
                if owned is not None
                else {"root_exited": True, "remaining_pids": []}
            )
            write_private(state / "stop-facts.json", json.dumps(stopped))
            emit(
                {
                    "state": "stopped",
                    "owned_process_stop": stopped,
                    "ownership_before_stop": ownership,
                }
            )
        else:
            emit({"state": "stopped"})


if __name__ == "__main__":
    main()

"""Opt-in cross-machine controller; messages enter only the production Receiver.

stdin carries private, test-only bootstrap material. stdout contains public
bindings and observations, never credentials. The model's only communication
channel is its independently authenticated ACS MCP instance.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.signing import SigningKey

from runtime.communication_tools import DESCRIPTIONS, adopt_catalog
from runtime.opencode_http import listener_owner_pids
from runtime.posix_process_supervisor import PosixProcessSupervisor
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import public_key, sign, tls_fingerprint
from runtime.receiver_deployment import (
    FactoryBinding,
    bind_process_config,
    dump_process_config,
    inspect_factory,
)
from runtime.receiver_entry import load_callbacks, load_process_config
from runtime.receiver_models import EndpointBinding
from runtime.remote_endpoint import ReceiverHTTPServer, RemoteNodeTransport
from runtime.supervisor import _proc_birth


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
    if hasattr(capacity.driver, "thread_id"):
        return {"codex": client.request("mcpServerStatus/list", {
            "threadId": capacity.driver.thread_id, "serverName": "acs", "detail": "toolsAndAuthOnly"}, timeout=60)}
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
    owners = sorted(listener_owner_pids(capacity.driver.client.port)) if hasattr(capacity.driver.client, "port") else []
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


def installed_events(state):
    path = state / "driver.sqlite"
    if not path.is_file():
        return []
    with sqlite3.connect(path) as connection:
        return [
            (kind, json.loads(body))
            for kind, body in connection.execute(
                "SELECT kind,body FROM driver_events ORDER BY sequence"
            )
        ]


def installed_health(state, port, fingerprint):
    connection = http.client.HTTPSConnection(
        "127.0.0.1", port, timeout=60, context=RemoteNodeTransport._context()
    )
    try:
        connection.connect()
        assert tls_fingerprint(connection.sock.getpeercert(binary_form=True)) == fingerprint
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        data = response.read(16385)
        assert response.status == 200 and len(data) <= 16384
        return json.loads(data)
    finally:
        connection.close()


def installed_mcp_status(state):
    """Test oracle reads only this installation's proven owned Native listener."""
    events = installed_events(state)
    started = next(body for kind, body in events if kind == "process_started")
    pid, birth = started["pid"], started["birth_ref"]
    endpoint = next(body["endpoint"] for kind, body in events if kind == "http_dispatch")
    port = urlsplit(endpoint).port

    def owned():
        return (
            _proc_birth(pid) == birth
            and bool(listener_owner_pids(port))
            and listener_owner_pids(port) <= set(PosixProcessSupervisor._members(pid))
        )

    assert owned(), "installed Native ownership changed before test authentication"
    environment = Path(f"/proc/{pid}/environ").read_bytes()
    password = next(
        value.split(b"=", 1)[1]
        for value in environment.split(b"\0")
        if value.startswith(b"OPENCODE_SERVER_PASSWORD=")
    )
    authorization = "Basic " + base64.b64encode(b"opencode:" + password).decode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.connect()
        assert owned(), "installed Native ownership changed before test request"
        connection.request(
            "GET",
            "/mcp?" + urlencode({"directory": str(state / "work")}),
            headers={"Authorization": authorization, "Accept": "application/json"},
        )
        response = connection.getresponse()
        data = response.read(65537)
        assert response.status == 200 and len(data) <= 65536
        return json.loads(data)
    finally:
        connection.close()


def installed_observation(state, port, fingerprint):
    started_at = time.monotonic()
    native = installed_health(state, port, fingerprint)
    events = installed_events(state)
    requests = [body for kind, body in events if kind == "http_dispatch"]
    with sqlite3.connect(state / "receiver.sqlite") as connection:
        admissions = connection.execute(
            "SELECT purpose,count(*) FROM receiver_requests GROUP BY purpose"
        ).fetchall()
    return {
        "state": "observed",
        "native": native,
        "health_seconds": time.monotonic() - started_at,
        "requests": admissions,
        "driver_requests": requests,
        "terminal_readbacks": sum(kind == "terminal_readback" for kind, _ in events),
        "event_subscriptions": sum(body.get("path") == "/event" for body in requests),
        "observation": "installed_console_health_and_actual_journals",
    }


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
    callbacks = server = worker = installed_process = None
    installed_launcher = None
    lose_acks = False
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
                shared = request.get("shared_profile", False)
                installed_launcher = request.get("installed_launcher")
                lose_acks = request.get("lose_dispatch_and_readback_acks", False)
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
                            "access_mode": "shared" if shared else "owner",
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
                    "import sys\nsys.dont_write_bytecode=True\nsys.path.insert(0,"
                    + repr(request.get("installed_site", str(ROOT)))
                    + ")\n"
                    + "sys.stderr=open("
                    + repr(str(state / "mcp.stderr.txt"))
                    + ",'a',buffering=1)\n"
                    + "import time\nprint('MCP import start',time.monotonic(),file=sys.stderr)\n"
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
                                "npm": "@ai-sdk/openai" if request.get("lose_dispatch_and_readback_acks") or request.get("provider_responses") else "@ai-sdk/openai-compatible",
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
                codex = request.get("harness") == "codex"
                factory_reference = "runtime_deployment.receiver_codex:callbacks" if codex else "runtime_deployment.receiver_opencode:callbacks"
                if codex:
                    from runtime_tests.fixtures.codex_shared_profile import configure
                    assert shared and not installed_launcher
                    settings = configure(state, work, wrapper, request, settings)
                elif shared:
                    from runtime.opencode_driver import COLLABORATION_TOOLS, file_digest
                    permissions = {"*": "deny", "task": "deny", **{"acs_" + tool: "allow" for tool in COLLABORATION_TOOLS}}
                    native["permission"] = permissions
                    native["agent"]["acs-peer"]["permission"] = permissions
                    native["agent"]["acs-peer"]["model"] = native["model"]
                    del os.environ["OPENCODE_CONFIG_CONTENT"]
                    # Each profile root is private and empty before first launch.
                    for field, directory in (("config_root", "restricted-config"), ("data_root", "restricted-data"),
                        ("state_root", "restricted-state"), ("cache_root", "restricted-cache")):
                        root = state / directory
                        root.mkdir(mode=0o700)
                        settings[field] = str(root)
                    config_path = Path(settings["config_root"]) / "opencode/opencode.json"
                    config_path.parent.mkdir(mode=0o700)
                    write_private(config_path, json.dumps(native))
                    schema = state / "openapi.json"
                    write_private(schema, json.dumps(request["shared_schema"]))
                    environment_dir = Path(f"/run/user/{os.getuid()}/acs-receiver-opencode/receiver-run-" + request["shared_run"] + "/systemd-env")
                    environment_dir.mkdir(mode=0o700, parents=True)
                    settings.update(executable_sha256=file_digest(request["binary"]), opencode_version="1.18.34",
                        schema_path=str(schema), schema_sha256=file_digest(schema), config_sha256=file_digest(config_path),
                        agent="acs-peer", provider_id="acs-test", model_id="gpt-6.1-sol", collaboration_server="acs",
                        systemd_environment_dir=str(environment_dir), environment_refs={
                            name: {"kind": "environment", "name": name} for name in
                            ("ACS_B_DSN", "ACS_B_CREDENTIAL", "ACS_B_PROVIDER_KEY")})
                if installed_launcher:
                    settings_path = state / "factory-settings.json"
                    write_private(settings_path, json.dumps(settings))
                    bound = subprocess.run(
                        [
                            installed_launcher,
                            "--factory-binding",
                            "--factory-reference",
                            factory_reference,
                            "--factory-settings",
                            str(settings_path),
                        ],
                        capture_output=True,
                        check=True,
                        timeout=30,
                    )
                    factory = FactoryBinding.model_validate_json(bound.stdout, strict=True)
                else:
                    factory, _, _, _ = inspect_factory(
                        factory_reference, settings=settings
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
                if installed_launcher:
                    with (
                        open(state / "receiver.stdout.txt", "wb") as output,
                        open(state / "receiver.stderr.txt", "wb") as errors,
                    ):
                        installed_process = subprocess.Popen(
                            [installed_launcher, "--config", str(state / "process.json")],
                            cwd=state,
                            env=dict(os.environ),
                            stdout=output,
                            stderr=errors,
                        )
                    while True:
                        assert installed_process.poll() is None, (
                            "installed Receiver exited; inspect its private stderr"
                        )
                        try:
                            native = installed_health(
                                state,
                                listen_port,
                                tls_fingerprint(cert.public_bytes(serialization.Encoding.DER)),
                            )
                            break
                        except (OSError, http.client.HTTPException):
                            assert time.monotonic() - started_at < 110, (
                                "installed Receiver startup did not become ready"
                            )
                            time.sleep(0.1)
                    mcp = (
                        installed_mcp_status(state) if os.environ.get("ACS_B_PROVIDER_KEY") else {}
                    )
                    safe_mcp = json.dumps(mcp)
                    for variable in ("ACS_B_PROVIDER_KEY", "ACS_B_CREDENTIAL"):
                        if os.environ.get(variable):
                            safe_mcp = safe_mcp.replace(os.environ[variable], "[redacted]")
                    mcp = json.loads(safe_mcp)
                    emit(
                        {
                            "state": "started",
                            "native": native,
                            "mcp": mcp,
                            "startup_seconds": time.monotonic() - started_at,
                            "receiver_entry": "installed_console_script",
                            "receiver_pid": installed_process.pid,
                        }
                    )
                    continue
                process = load_process_config(state / "process.json")
                if process.runtime.access_mode == "shared":
                    from runtime.opencode_driver import OpenCodeNativeDriver
                    from runtime.systemd_supervisor import SystemdUserSupervisor
                    original_control = SystemdUserSupervisor._run_systemctl
                    def recorded_control(arguments, *args, original_control=original_control, state=state, **kwargs):
                        if "stop" in arguments:
                            import traceback
                            with (state / "supervisor-stop.private.txt").open("a") as trace:
                                traceback.print_stack(limit=12, file=trace)
                        return original_control(arguments, *args, **kwargs)
                    SystemdUserSupervisor._run_systemctl = staticmethod(recorded_control)
                    diagnostic_lock = threading.Lock()
                    diagnostic = state / "native.private.log"
                    def retained_output(driver, stream, diagnostic=diagnostic, diagnostic_lock=diagnostic_lock):
                        try:
                            while chunk := stream.read1(4096):
                                with driver._diag_lock:
                                    driver._diag_bytes += len(chunk)
                                    driver._diag_hash.update(chunk)
                                with diagnostic_lock:
                                    size = diagnostic.stat().st_size if diagnostic.exists() else 0
                                    if size < 1_048_576:
                                        with diagnostic.open("ab") as output:
                                            output.write(chunk[:1_048_576-size])
                                        diagnostic.chmod(0o600)
                        except (OSError, ValueError):
                            pass
                    OpenCodeNativeDriver._drain_output = retained_output
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
                dropped_acks = []
                if lose_acks:
                    original_drop = server.drop_response

                    def drop_committed_ack(purpose, drops=dropped_acks, fallback=original_drop):
                        if purpose == "delivery.readback" or purpose == "delivery.dispatch" and purpose not in drops:
                            if purpose not in drops:
                                drops.append(purpose)
                            return True
                        return fallback(purpose)

                    # Real TLS responses are closed after the official receiver
                    # committed its result. The Native driver and B are unchanged.
                    server.drop_response = drop_committed_ack
                server.test_dropped_acks = dropped_acks
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
            elif action == "sandbox_probe":
                from runtime_tests.fixtures.codex_shared_profile import sandbox_probe
                emit({"state": "sandbox_probed", "evidence": sandbox_probe(callbacks.native_invoke.__self__, state)})
            elif action == "observe":
                if installed_launcher:
                    emit(
                        installed_observation(
                            state,
                            listen_port,
                            tls_fingerprint(cert.public_bytes(serialization.Encoding.DER)),
                        )
                    )
                    continue
                capacity = callbacks.native_invoke.__self__
                read_at = time.monotonic()
                native = capacity.health()
                health_seconds = time.monotonic() - read_at
                with capacity.journal._connect() as connection:
                    events = [
                        json.loads(row[0])
                        for row in connection.execute(
                            "SELECT body FROM driver_events WHERE kind IN ('http_dispatch','rpc_dispatch')"
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
                        "event_subscription": getattr(capacity.driver, "_event_thread", None) is not None,
                        "dropped_ack_purposes": server.test_dropped_acks,
                        **({"owned_snapshot": capacity.supervisor.inspect(capacity.driver.owned)}
                           if process.runtime.access_mode == "shared" else {}),
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
        if installed_process is not None:
            events = installed_events(state)
            started = next((body for kind, body in events if kind == "process_started"), None)
            if installed_process.poll() is None:
                installed_process.terminate()
            receiver_exit = installed_process.wait(timeout=30)
            remaining = PosixProcessSupervisor._members(started["pid"]) if started else []
            stopped = {
                "scope": "owned_process_group",
                "subtree_containment": False,
                "root_exited": _proc_birth(started["pid"]) != started["birth_ref"]
                if started
                else True,
                "remaining_pids": remaining,
                "receiver_exit_code": receiver_exit,
                "observation": "actual_console_exit_and_proc_readback",
            }
            write_private(state / "stop-facts.json", json.dumps(stopped))
            emit({"state": "stopped", "owned_process_stop": stopped})
        elif callbacks is not None:
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

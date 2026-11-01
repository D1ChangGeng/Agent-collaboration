"""Explicitly opted-in physical Windows -> Linux signed Receiver qualification.

Only .py/.sql source is uploaded to a new /tmp directory. The formal checkout
and services are read-only. SSH carries the end-to-end TLS stream; it does not
substitute for signed Receiver admission or for B's own ACS MCP reply.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nacl.signing import SigningKey
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime.communication_tools import DESCRIPTIONS
from runtime.delivery_models import EndpointBindingRequest
from runtime.domain import DomainAuthority
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    RuntimeRegistration,
)
from runtime.machine_connections import ConfiguredRemoteEndpoint
from runtime.receiver_crypto import public_key
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import EndpointRegistration
from runtime.surface_config import PrivateReference, RemoteEndpointSettings
from runtime_tests.test_communication import CATALOG, await_waiter, call, prepare_ordinary_agents
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command as bind_command
from runtime_tests.test_receiver_domain_delivery import command as receiver_command

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


def dispatch_committed(comm, sent):
    """Drive the actual external dispatcher, retaining one committed identity.

    A pre-call busy/unknown observation can defer this same prepared Attempt.
    A possible Native effect ends this loop as uncertain; it is never retried.
    """
    identity = {
        "tenant_id": comm.authority.tenant_id,
        "message_id": sent["message_id"],
        "operation_id": sent["operation_id"],
    }
    end = time.monotonic() + 180
    while True:
        result = comm.dispatcher.dispatch(identity)
        if result["status"] not in {"retry_wait", "busy"}:
            return result
        assert time.monotonic() < end, result
        time.sleep(0.25)


def launch_codex(
    comm, tmp_path, provider_key, endpoint_id=None, transport_seed=None, *, prompt=None
):
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    assert binary, "an actual installed Codex CLI is required"
    home = tmp_path / "codex-a"
    home.mkdir(mode=0o700)
    config = [
        'model="gpt-6.1-sol"',
        'model_provider="acs-test"',
        'approval_policy="never"',
        'sandbox_mode="read-only"',
        "project_doc_max_bytes=0",
        "[features]",
        "apps=false",
        "plugins=false",
        "[model_providers.acs-test]",
        'name="Approved isolated Provider"',
        'base_url="https://api.payapionline.top/v1"',
        'env_key="ACS_A_PROVIDER_KEY"',
        'wire_api="responses"',
        "requires_openai_auth=true",
    ]
    for path in sorted((Path.home() / ".agents/skills").glob("*/SKILL.md")):
        config.extend(
            ["[[skills.config]]", "path=" + json.dumps(str(path.resolve())), "enabled=false"]
        )
    (home / "config.toml").write_text("\n".join(config) + "\n", encoding="utf-8")
    (home / "config.toml").chmod(0o600)
    surface = tmp_path / "a-surface.json"
    surface.write_text(
        json.dumps(
            {
                "access_mode": comm.authority.access_mode,
                "context": asdict(comm.clients["a"].service.context),
                **(
                    {
                        "remote_endpoints": [
                            {
                                "endpoint_id": endpoint_id,
                                "authority_signing_key_ref": {
                                    "kind": "environment",
                                    "name": "ACS_A_TRANSPORT_SEED",
                                },
                            }
                        ]
                    }
                    if endpoint_id
                    else {"delivery_maintenance": "external"}
                ),
                "dsn_ref": {"kind": "environment", "name": "ACS_A_DSN"},
                "credential_ref": {"kind": "environment", "name": "ACS_A_CREDENTIAL"},
            }
        ),
        encoding="utf-8",
    )
    surface.chmod(0o600)
    wrapper = tmp_path / "a-mcp.py"
    wrapper.write_text(
        "import sys\nsys.path.insert(0,"
        + repr(str(ROOT))
        + ")\nsys.stderr=open(" + repr(str(tmp_path / "a-mcp.stderr.txt")) + ",'a',buffering=1)\n"
        + "from runtime.project_entry import main\n"
        "raise SystemExit(main("
        + repr(
            [
                "--config",
                str(surface),
                "--catalog",
                str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
                "--profile",
                "engineer",
            ]
        )
        + "))\n",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("CODEX_", "OPENCODE_", "ACS_REMOTE_", "ACS_MATRIX_", "ACS_RECEIVER_")
        )
    }
    env.update(
        CODEX_HOME=str(home),
        ACS_A_PROVIDER_KEY=provider_key,
        ACS_A_DSN=comm.dsn,
        ACS_A_CREDENTIAL=comm.clients["a"].credential_provider(),
        ACS_A_TRANSPORT_SEED=transport_seed or "",
    )
    declaration = (
        "mcp_servers={acs={command="
        + json.dumps(sys.executable)
        + ",args=["
        + json.dumps(str(wrapper))
        + "],"
        'env_vars=["ACS_A_DSN","ACS_A_CREDENTIAL","ACS_A_TRANSPORT_SEED"],required=true,startup_timeout_sec=30,tool_timeout_sec=360,'
        'tools={send_message={approval_mode="approve"}}}}'
    )
    out = (tmp_path / "a.jsonl").open("w", encoding="utf-8")
    err = (tmp_path / "a.stderr.txt").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            binary,
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-C",
            str(tmp_path),
            "-c",
            declaration,
            prompt
            or (
                "You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for the release label of this isolated "
                "exercise using ACS. The normal send defaults can activate B. Wait for B's actual ACS reply and report the exact "
                "label. Use ACS MCP tools; do not inspect or change files."
            ),
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=err,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return process, (out, err)


@pytest.mark.skipif(
    os.getenv("ACS_REAL_REMOTE_NATIVE_TEST") != "1",
    reason="source upload, physical SSH host and actual Native capacity are explicit opt-in",
)
@pytest.mark.parametrize("sender_mode", ["lifecycle", "scripted", "codex"])
def test_physical_signed_receiver_and_independent_reply(comm, tmp_path, monkeypatch, sender_mode):
    if sender_mode != "lifecycle" and os.getenv("ACS_REAL_REMOTE_MODEL_TEST") != "1":
        pytest.skip("actual approved Provider model requests are separately opt-in")
    local_wsl = os.getenv("ACS_NATIVE_LOCAL_WSL")
    installed_launcher = os.getenv("ACS_INSTALLED_NATIVE_RECEIVER")
    shared = os.getenv("ACS_NATIVE_SHARED_PROFILE") == "1"
    mode = "shared" if shared else "owner"
    if shared:
        original_failure = comm.dispatcher._failure
        def retain_dispatch_failure(cursor, row, error):
            import traceback
            with (tmp_path / "dispatch-error.private.txt").open("a") as errors:
                traceback.print_exception(error, file=errors)
            return original_failure(cursor, row, error)
        monkeypatch.setattr(comm.dispatcher, "_failure", retain_dispatch_failure)
    def command(*args, **kwargs):
        value = receiver_command(*args, **kwargs)
        return value.model_copy(update={"deadline": datetime.now(UTC) + timedelta(minutes=5)}) if shared else value
    host = "wsl:" + local_wsl if local_wsl else os.environ["ACS_REMOTE_SSH_HOST"]
    remote_python = os.environ["ACS_REMOTE_PYTHON"]
    remote_binary = os.environ["ACS_REMOTE_OPENCODE"]
    assert host and not host.startswith("-")
    assert remote_python.startswith("/tmp/") and remote_binary.startswith("/")
    ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    control = (
        (["bash", "-c"] if os.name == "posix" else ["wsl.exe", "-d", local_wsl, "--", "bash", "-c"])
        if local_wsl
        else [*ssh, host]
    )
    remote_root = "/tmp/acs-remote-native-" + uuid.uuid4().hex

    def remote(text, timeout=45):
        result = subprocess.run([*control, text], capture_output=True, timeout=timeout, check=False)
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-1500:]
        return result.stdout.decode().strip()

    files = [
        path
        for folder in (ROOT / "runtime", ROOT / "runtime_deployment")
        for path in folder.glob("*")
        if path.suffix in {".py", ".sql"}
    ]
    files += [ROOT / "runtime_tests/fixtures/remote_native_receiver.py", Path(__file__)]
    if os.getenv("ACS_TEST_NATIVE_ACK_LOSS") == "1":
        files.append(ROOT / "runtime_tests/test_communication_ack_loss_native.py")
    manifest = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    (tmp_path / "source-files.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as pack:
        for path in files:
            info = pack.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
            info.mode = 0o600
            with path.open("rb") as source:
                pack.addfile(info, source)
    remote("mkdir -m 700 " + shlex.quote(remote_root))
    if local_wsl:
        mounted_archive = (
            str(archive)
            if os.name == "posix"
            else subprocess.check_output(
                ["wsl.exe", "-d", local_wsl, "--", "wslpath", "-a", "-u", archive.as_posix()],
                text=True,
            ).strip()
        )
        remote(
            "cp " + shlex.quote(mounted_archive) + " " + shlex.quote(remote_root + "/source.tar")
        )
    else:
        upload = subprocess.run(
            ["scp", "-q", str(archive), host + ":" + remote_root + "/source.tar"],
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert upload.returncode == 0, upload.stderr
    remote("tar -xf " + remote_root + "/source.tar -C " + remote_root)
    values = conninfo_to_dict(comm.dsn)
    assert values["host"] == "127.0.0.1" and values["dbname"] == "acs_communication_test"
    remote_db_port = (
        int(values["port"])
        if local_wsl
        else int(
            remote(
                "python3 -c "
                + shlex.quote(
                    "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1])"
                )
            )
        )
    )
    public_port = free_port()
    tunnel = actor = a = None
    outputs = []
    received = queue.Queue()
    wire = (tmp_path / "receiver-controller.jsonl").open("w", encoding="utf-8")
    errors = (tmp_path / "receiver-controller.stderr.txt").open("w", encoding="utf-8")
    outputs.extend((wire, errors))
    facts = {
        "remote_root": remote_root,
        "ssh_host": host,
        "sender_mode": sender_mode,
        "receiver_entry": "current source load_process_config/load_callbacks/ReceiverHTTPServer; installed entry not measured",
        "topology": ("local-linux" if os.name == "posix" else "windows-to-wsl-same-machine")
        if local_wsl
        else "physical-ssh-host",
    }
    if installed_launcher:
        facts["receiver_entry"] = "installed_console_script"
        facts["installed_launcher"] = installed_launcher

    def read_responses():
        for line in actor.stdout:
            wire.write(line.decode())
            wire.flush()
            received.put(json.loads(line))
        received.put({"state": "controller_exited"})

    def rpc(request=None, timeout=60):
        if request is not None:
            actor.stdin.write((json.dumps(request) + "\n").encode())
            actor.stdin.flush()
        result = received.get(timeout=timeout)
        assert result.get("state") != "controller_exited", "remote controller exited; see stderr"
        return result

    try:
        catalog_path = os.environ["ACS_REMOTE_BASE_CATALOG"]
        actor = subprocess.Popen(
            [
                *control,
                "ACS_REMOTE_BASE_CATALOG="
                + shlex.quote(catalog_path)
                + " "
                + shlex.quote(remote_python)
                + " "
                + remote_root
                + "/runtime_tests/fixtures/remote_native_receiver.py",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
        )
        reader = threading.Thread(target=read_responses, daemon=True)
        reader.start()
        prepared = rpc()
        assert prepared["source_files"] == manifest, "remote source differs"
        expected_contract = {
            name: {
                key: CATALOG["tools"][name][key]
                for key in ("description", "input_schema", "security_scopes")
            }
            for name in DESCRIPTIONS
        }
        assert prepared["contract"] == expected_contract, (
            "remote ordinary communication contract differs"
        )
        facts.update(hostname=prepared["hostname"], source_files=manifest)
        if local_wsl:
            public_port = prepared["listen_port"]
        else:
            tunnel = subprocess.Popen(
                [
                    *ssh,
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-N",
                    "-R",
                    f"127.0.0.1:{remote_db_port}:127.0.0.1:{values['port']}",
                    "-L",
                    f"127.0.0.1:{public_port}:127.0.0.1:{prepared['listen_port']}",
                    host,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        manager = comm.clients["a"]
        # Native Owner receiver and its technical registration share the Owner
        # authority policy. A/B retain ordinary, distinct MCP credentials.
        comm.authority.access_mode = mode
        prepare_ordinary_agents(comm, tmp_path)
        comm.clients["manager"] = manager
        for client in comm.clients.values():
            client.service.service.authority.access_mode = mode
        facts["actor_profiles"] = {
            name: {
                "profile": comm.clients[name].service.profile,
                "principal_ref": comm.clients[name].service.context.principal_ref,
                "access_mode": mode,
            }
            for name in ("a", "b")
        }
        observer_ctx = replace(
            comm.authority.context, principal_ref="node:remote-test", grant_ref="grant:remote-node"
        )
        observer = DomainAuthority(comm.dsn, context=observer_ctx, access_mode=mode)
        with comm.authority._connect() as connection:
            connection.execute(
                "UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref=%s",
                (
                    json.dumps(["receiver.manage", "enrollment.manage"]),
                    comm.authority.context.grant_ref,
                ),
            )
            connection.execute(
                "INSERT INTO grants SELECT %s,tenant_id,%s,authority_id,authority_incarnation,scope_id,%s,"
                "expires_at,NULL FROM grants WHERE grant_ref=%s",
                (
                    observer_ctx.grant_ref,
                    observer_ctx.principal_ref,
                    json.dumps(["runtime.register", "endpoint.register"]),
                    comm.authority.context.grant_ref,
                ),
            )
        node_id, runtime_id, endpoint_id, boot = (
            "remote-node",
            "remote-runtime",
            "remote-opencode-endpoint",
            "isolated-boot",
        )
        expiry = datetime.now(UTC) + timedelta(hours=1)
        comm.authority.enroll_node(
            command(comm.authority, "node.enroll", "node", node_id),
            NodeEnrollment(
                scope_id="local-scope",
                agent_slot_id="slot-b",
                observer_grant_ref=observer_ctx.grant_ref,
                machine_id="1302-1",
                boot_incarnation=boot,
                public_key=prepared["node_public_key"],
                expires_at=expiry,
            ),
        )

        def proof(purpose_command, node_input):
            challenge = observer.challenge_node(
                command(observer, "node.challenge", "node", node_id, 1),
                NodeChallengeRequest(
                    purpose=purpose_command.command_type,
                    purpose_command_id=purpose_command.command_id,
                    purpose_hash=EnrollmentAuthority.signing_hash(purpose_command, node_input),
                    ttl_seconds=300 if shared else 120,
                ),
            )
            signature = rpc({"action": "sign", "message_hex": challenge.message_hex})["signature"]
            return NodeCommandProof(challenge_id=challenge.challenge_id, signature=signature)

        runtime = RuntimeRegistration(
            node_id=node_id,
            node_binding_revision=1,
            provider="receiver-tls",
            producer_grant_ref=observer_ctx.grant_ref,
            expires_at=expiry,
        )
        envelope = command(observer, "runtime.register", "runtime", runtime_id)
        observer.register_runtime(
            envelope, runtime, proof(envelope, {"request": runtime.model_dump(mode="json")})
        )
        authority_key = SigningKey.generate()
        comm.authority.register_authority_transport_key(
            command(
                comm.authority, "receiver.key.register", "authority_transport_key", "remote-key"
            ),
            AuthorityTransportKeyRegistration(
                key_id="remote-key",
                revision=1,
                public_key=public_key(authority_key),
                expires_at=expiry,
            ),
        )
        comm.authority.register_receiver_connection(
            command(comm.authority, "receiver.connection.register", "connection", "remote-tunnel"),
            ConnectionReferenceRegistration(
                connection_ref="remote-tunnel",
                revision=1,
                locator_host="127.0.0.1",
                locator_port=public_port,
                route_class="loopback" if local_wsl else "tunnel",
                policy_digest="c" * 64,
                expires_at=expiry,
            ),
        )
        registration = EndpointRegistration(
            registration_id="remote-registration",
            endpoint_id=endpoint_id,
            endpoint_revision=1,
            connection_ref="remote-tunnel",
            tenant_id=comm.authority.tenant_id,
            authority_id=comm.authority.context.authority_id,
            authority_incarnation=comm.authority.context.authority_incarnation,
            node_id=node_id,
            node_binding_revision=1,
            runtime_id=runtime_id,
            runtime_revision=1,
            machine_id="1302-1",
            boot_incarnation=boot,
            scope_id="local-scope",
            agent_slot_id="slot-b",
            tls_certificate_sha256=prepared["certificate_sha256"],
            config_sha256="0" * 64,
            expires_at=expiry,
        )
        with comm.authority._connect() as connection:
            node_key_id = connection.execute(
                "SELECT key_id FROM enrolled_node_bindings WHERE node_id=%s", (node_id,)
            ).fetchone()[0]
        provider_key = os.environ["ACS_REMOTE_PROVIDER_KEY"] if sender_mode != "lifecycle" or shared else None
        label = "remote-cedar-" + uuid.uuid4().hex[:12]
        configured = rpc(
            {
                "action": "configure",
                "binary": remote_binary,
                "dsn": make_conninfo(comm.dsn, port=remote_db_port),
                "credential": comm.clients["b"].credential_provider(),
                "context": asdict(comm.clients["b"].service.context),
                "provider_key": provider_key,
                "label": label,
                "lose_dispatch_and_readback_acks": os.getenv("ACS_TEST_NATIVE_ACK_LOSS") == "1",
                "provider_responses": os.getenv("ACS_NATIVE_PROVIDER_RESPONSES") == "1",
                **({"shared_profile": True, "shared_run": uuid.uuid4().hex,
                    "shared_schema": json.loads(Path(os.environ["ACS_SHARED_OPENCODE_SCHEMA"]).read_text())} if shared else {}),
                **(
                    {
                        "installed_launcher": installed_launcher,
                        "installed_site": os.environ["ACS_INSTALLED_NATIVE_SITE"],
                    }
                    if installed_launcher
                    else {}
                ),
                "binding": {
                    "registration": registration.model_dump(mode="json"),
                    "locator_host": "127.0.0.1",
                    "locator_port": public_port,
                    "route_class": "loopback" if local_wsl else "tunnel",
                    "node_key_id": node_key_id,
                    "node_public_key": prepared["node_public_key"],
                    "registration_signature": "0" * 128,
                },
                "client_config": {
                    "authority_key_id": "remote-key",
                    "authority_key_revision": 1,
                    "authority_public_key": public_key(authority_key),
                    "authority_public_key_fingerprint": hashlib.sha256(
                        bytes.fromhex(public_key(authority_key))
                    ).hexdigest(),
                    "expected_boot_incarnation": boot,
                    "journal_generation": 1,
                    "access_mode": mode,
                },
            }
        )
        registration = EndpointRegistration.model_validate_json(
            json.dumps(configured["registration"]), strict=True
        )
        envelope = command(observer, "endpoint.register", "endpoint", endpoint_id)
        node_input = {
            "registration": registration.model_dump(mode="json"),
            "registration_signature": configured["registration_signature"],
        }
        observer.register_receiver_endpoint(
            envelope,
            EndpointRegistrationCommand(
                registration=registration,
                registration_signature=configured["registration_signature"],
                proof=proof(envelope, node_input),
            ),
        )
        started = rpc({"action": "start"}, timeout=120)
        facts["native_start"] = started
        assert started["native"]["session_ref"].startswith("ses_")
        if sender_mode != "lifecycle":
            assert started["mcp"].get("acs", {}).get("status") == "connected", started["mcp"]
        monkeypatch.setenv("ACS_TEST_AUTHORITY_SIGNING_KEY", authority_key.encode().hex())
        endpoint = ConfiguredRemoteEndpoint(
            comm.authority,
            RemoteEndpointSettings(
                endpoint_id=endpoint_id,
                request_timeout_seconds=30 if shared else 5,
                authority_signing_key_ref=PrivateReference(
                    kind="environment", name="ACS_TEST_AUTHORITY_SIGNING_KEY"
                ),
            ),
        )
        comm.dispatcher.service.endpoints[endpoint_id] = endpoint
        comm.authority._delivery_endpoints[endpoint_id] = endpoint
        comm.dispatcher.service.bind_endpoint(
            bind_command(comm.authority, "message.bind", endpoint_id),
            EndpointBindingRequest(
                scope_id="local-scope", agent_slot_id="slot-b", expires_at=expiry
            ),
        )
        try:
            health_at = time.monotonic()
            facts["direct_transport_health"] = endpoint._adapter().transport.inspect_runtime()
            facts["direct_transport_health_seconds"] = time.monotonic() - health_at
        except (OSError, RuntimeError, ValueError) as error:
            facts["direct_transport_health"] = {
                "error_type": type(error).__name__,
                "message": str(error),
            }
        observed = call(
            comm,
            "manager",
            "configure_team",
            members=[
                {"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": endpoint_id}
            ],
        )
        facts["configuration"] = observed
        facts["post_configuration_health"] = endpoint.inspect_runtime()
        facts["remote_direct_observation"] = rpc({"action": "observe"})
        assert (
            observed["data"]["native_sessions"][0]["session_ref"]
            == started["native"]["session_ref"]
        ), observed
        assert facts["post_configuration_health"]["state"] in {"idle", "busy", "unknown"}, facts[
            "post_configuration_health"
        ]
        if facts["post_configuration_health"]["state"] == "unknown":
            assert facts["post_configuration_health"].get("session_ref") is None
        facts.update(
            tls_sha256=prepared["certificate_sha256"],
            native=started["native"],
            startup_seconds=started["startup_seconds"],
            configuration=observed,
        )
        if sender_mode != "lifecycle":
            start = time.monotonic()
            if sender_mode == "scripted":
                sent = call(
                    comm,
                    "a",
                    "send_message",
                    to="collaborator:project-alpha:slot-b",
                    content="What is the release label for this isolated exercise? Please reply through ACS.",
                )["data"]
                with ThreadPoolExecutor(max_workers=1) as pool:
                    waiting = pool.submit(
                        call,
                        comm,
                        "a",
                        "wait_for_response",
                        handles=[sent["message_handle"]],
                        timeout_seconds=120 if shared else 300,
                    )
                    await_waiter(comm)
                    dispatched = dispatch_committed(comm, sent)
                    assert dispatched["status"] in {"delivered", "uncertain"}, dispatched
                    response = waiting.result(timeout=310)
            else:
                ack_loss = os.getenv("ACS_TEST_NATIVE_ACK_LOSS") == "1"
                a, a_outputs = launch_codex(
                    comm, tmp_path, provider_key, endpoint_id, authority_key.encode().hex(),
                    prompt=("You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for the release label "
                        "using one normal ACS send_message with invoke + async. Call wait_for_response on the returned "
                        "handle with timeout_seconds=0, retain that handle and finish this turn. A new client context "
                        "will continue the same exchange. Do not send again. Use ACS tools only; do not inspect files."
                        if ack_loss else ("You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for its "
                            "release label using send_message with activation=invoke and response_mode=async. Retain the "
                            "returned original message handle. Call wait_for_response with that handle and timeout_seconds=300 "
                            "to wait for B's explicit related reply. If still pending, continue waiting on that same handle. "
                            "Finish only after reporting B's exact label. Use normal ACS tools and keep the original request identity."
                            if shared else None)),
                )
                outputs.extend(a_outputs)
                deadline = time.monotonic() + 150
                while True:
                    with comm.authority._connect() as connection:
                        row = connection.execute(
                            "SELECT message_id,operation_id FROM delivery_messages WHERE packet_json->>'sender'=%s",
                            ("collaborator:project-alpha:slot-a-real",),
                        ).fetchone()
                    if row:
                        break
                    assert a.poll() is None and time.monotonic() < deadline, (
                        "Codex A did not submit; see raw log"
                    )
                    time.sleep(0.2)
                sent = {
                    "message_id": row[0],
                    "operation_id": row[1],
                    "message_handle": "message:project-alpha:" + row[0],
                }
                # The actual stdio MCP entry owns default maintenance. The
                # evaluator only observes this committed operation and never
                # calls dispatch/recovery or forwards an input to B.
                assert a.wait(timeout=600 if shared else 360) == 0
                observed_end = time.monotonic() + 60
                while True:
                    with comm.authority._connect() as connection:
                        state = connection.execute(
                            "SELECT state,receipt_high_water,attempts FROM delivery_messages WHERE message_id=%s",
                            (sent["message_id"],),
                        ).fetchone()
                    if state[0] in {"delivered", "uncertain"}:
                        break
                    assert time.monotonic() < observed_end, state
                    time.sleep(0.2)
                dispatched = {
                    "status": state[0],
                    "receipt_high_water": state[1],
                    "attempts": state[2],
                    "source": "default_stdio_maintenance",
                }
                facts["evaluator_dispatch_calls"] = 0
                if ack_loss:
                    # This is the handle from A's successful normal send, not a
                    # response copied from B or a synthetic recovery message.
                    assert sent["message_handle"] in (tmp_path / "a.jsonl").read_text(encoding="utf-8")
                    continued = tmp_path / "a-reconnected"
                    continued.mkdir()
                    a, a_outputs = launch_codex(comm, continued, provider_key, endpoint_id, authority_key.encode().hex(),
                        prompt="You are a fresh ordinary Agent A context in ACS project-alpha, continuing your own "
                        "already committed message " + sent["message_handle"] + ". Use wait_for_response with that "
                        "original handle and timeout_seconds=300, then read_message and report B's release label. "
                        "A transport acknowledgement may be unknown; only B's explicit related ACS message is a reply. "
                        "Do not call send_message or invoke again. Use ACS tools only; do not inspect files.")
                    outputs.extend(a_outputs)
                    assert a.wait(timeout=360) == 0
                    assert label in (continued / "a.jsonl").read_text(encoding="utf-8")
                    facts["sender_context_replaced"] = True
                else:
                    assert label in (tmp_path / "a.jsonl").read_text(encoding="utf-8")
                response = call(
                    comm,
                    "a",
                    "wait_for_response",
                    handles=[sent["message_handle"]],
                    timeout_seconds=0,
                )
            assert response["state"] == "satisfied", response
            reply = response["data"]["observations"][0]["reply"]
            assert (
                reply["from"] == "collaborator:project-alpha:slot-b" and label in reply["content"]
            )
            facts.update(
                request=sent,
                reply=reply,
                dispatch=dispatched,
                model_elapsed_seconds=time.monotonic() - start,
            )
        observation = rpc({"action": "observe"})
        if shared and sender_mode == "lifecycle":
            samples = []
            until = time.monotonic() + int(os.getenv("ACS_SHARED_IDLE_SECONDS", "120"))
            while time.monotonic() < until:
                samples.append(rpc({"action": "observe"}))
                time.sleep(2)
            facts["idle_samples"] = samples
            assert samples and all(s["native"]["state"] == "idle" and not s["owned_snapshot"]["root_exited"] for s in samples)
        facts["receiver"] = observation
        if os.getenv("ACS_TEST_NATIVE_ACK_LOSS") == "1":
            assert not installed_launcher, "This fault is injected in the source Receiver transport fixture"
            assert observation["dropped_ack_purposes"] == ["delivery.dispatch", "delivery.readback"]
            assert dispatched["status"] == "uncertain", dispatched
            assert dispatched["attempts"] == 1
            with comm.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM delivery_attempts WHERE message_id=%s",
                    (sent["message_id"],)).fetchone() == (1,)
            facts["ack_loss"] = {"response_drops_after_commit": observation["dropped_ack_purposes"],
                "native_prompt_count": 1, "core_delivery_state": "uncertain", "reply_wait_state": response["state"]}
        prompts = [
            row
            for row in observation["driver_requests"]
            if row.get("method") == "POST" and "prompt_async" in row.get("path", "")
        ]
        assert len(prompts) == (0 if sender_mode == "lifecycle" else 1)
        if installed_launcher:
            assert observation["terminal_readbacks"] == observation["event_subscriptions"] == 0
        else:
            assert not observation["collector"] and not observation["event_subscription"]
        with comm.authority._connect() as connection:
            counts = connection.execute(
                "SELECT (SELECT count(*) FROM communication_messages),"
                "(SELECT count(*) FROM communication_replies),to_regclass('work_items')"
            ).fetchone()
        assert counts == ((0, 0, None) if sender_mode == "lifecycle" else (2, 1, None)), counts
        facts["authority_counts"] = counts
    finally:
        try:
            if a is not None and a.poll() is None:
                a.terminate()
                a.wait(timeout=15)
        finally:
            try:
                if actor is not None:
                    try:
                        if actor.poll() is None:
                            try:
                                facts["stop"] = rpc({"action": "stop"}, timeout=30)
                                if "owned_process_stop" in facts["stop"]:
                                    assert (
                                        facts["stop"]["owned_process_stop"]["root_exited"] is True
                                    )
                            finally:
                                actor.stdin.close()
                                actor.wait(timeout=30)
                    finally:
                        actor.stdout.close()
            finally:
                try:
                    if tunnel is not None:
                        tunnel.terminate()
                        tunnel.wait(timeout=15)
                        tunnel.stderr.close()
                finally:
                    for output in outputs:
                        output.close()
                    (tmp_path / "facts.json").write_text(
                        json.dumps(facts, indent=2), encoding="utf-8"
                    )
    assert all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
        for name, digest in manifest.items()
    )

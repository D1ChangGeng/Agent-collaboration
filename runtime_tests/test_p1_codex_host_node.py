"""Host-only Codex Gate transport over the actual Domain/Node delivery path."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.delivery import DeliveryDispatcher
from runtime.delivery_models import (
    DeliveryPacket,
    EndpointBindingRequest,
    InvocationObservation,
)
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
    CodexHostRunPolicy,
    CodexHostUnixServer,
    HostNodeRejected,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_tests.test_delivery import command, query
from tools.runtime.p1_codex_host_scene import (
    CodexHostSceneService,
    TemporalHostDispatcher,
)
from tools.runtime.p1_codex_lifecycle import (
    DECISION_ID,
    MODEL_PROMPT,
    project_original_terminal,
)


def _scope_policy_hash(setup):
    value = query(setup, "SELECT policy FROM scopes WHERE scope_id='local-scope'")[0][0]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _host(setup, tmp_path, *, deadline_seconds=60):
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("host Node requires a non-root POSIX owner")
    private = tmp_path / "host-only"
    private.mkdir(mode=0o700)
    native = private / "codex"
    native.write_bytes(b"no-model-native-fixture\n")
    native.chmod(0o500)
    config = private / "config.toml"
    config.write_bytes(b"no-model-config-fixture\n")
    config.chmod(0o600)
    policy = CodexHostRunPolicy(
        run_id="p1-codex-" + uuid.uuid4().hex,
        tenant_id=setup.authority.tenant_id,
        authority_id=setup.authority.context.authority_id,
        authority_incarnation=setup.authority.context.authority_incarnation,
        scope_id="local-scope",
        agent_slot_id="local-slot",
        scope_policy_sha256=_scope_policy_hash(setup),
        endpoint_id="endpoint",
        source_commit="a" * 40,
        native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        deadline=datetime.now(UTC) + timedelta(seconds=deadline_seconds),
    )
    setup.authority.create_work_item(
        command(setup.authority, "work_item.create", "work-p1"),
        "local-scope",
        "local-slot",
        policy.source_commit,
    )
    host = CodexHostNodeEndpoint(
        policy,
        setup.dispatcher,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    return host, native, config, private


def _send(setup, policy, *, changed_run=None, binding_revision=1):
    message_id = "message-" + uuid.uuid4().hex
    cmd = command(
        setup.authority, "message.send", message_id, correlation_id=changed_run or policy.run_id
    )
    packet = DeliveryPacket(
        work_item_id="work-p1",
        target_scope_id="local-scope",
        target_agent_slot_id="local-slot",
        accepted_revision=0,
        goal="Observe a fixed no-model host Node delivery",
        accepted_state_summary="genesis revision zero",
        request="bounded fixture request",
        source_baseline=policy.source_commit,
        expected_response="durable receipts",
        activation="invoke",
        deadline=datetime.now(UTC) + timedelta(seconds=45),
        maximum_attempts=1,
    )
    result = setup.service.send_message(
        cmd, packet, endpoint_id=policy.endpoint_id, binding_revision=binding_revision
    )
    return CodexHostRequest(
        action="dispatch",
        run_id=policy.run_id,
        tenant_id=policy.tenant_id,
        message_id=message_id,
        command_id=cmd.command_id,
        operation_id=result.operation_id,
        endpoint_id=policy.endpoint_id,
        source_commit=policy.source_commit,
        native_sha256=policy.native_sha256,
        config_sha256=policy.config_sha256,
    )


def _systemd_fixture_driver(supervisor, run_id):
    class NoModelSystemdDriver:
        evidence_class = "fixture_callback"

        def __init__(self):
            self.calls = []
            self.proofs = []
            self.supervisor = supervisor
            self.owned = None

        def spawn(self, _operation):
            if self.owned is not None:
                raise RuntimeError("fixture host process is already owned")
            fixture = Path(__file__).parent / "systemd_jsonl_fixture.py"
            self.owned = supervisor.launch(
                [sys.executable, str(fixture)],
                cwd=str(fixture.parent),
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                label=run_id,
            )

        @staticmethod
        def prepare(invocation):
            return invocation

        def invoke(self, invocation):
            self.calls.append(invocation.operation_id)
            prestarted = self.owned is not None
            if not prestarted:
                self.spawn(None)
            owned = self.owned
            try:
                owned.process.stdin.write(b'{"command":"ping","value":"host-node"}\n')
                owned.process.stdin.flush()
                answer = json.loads(owned.process.stdout.readline())
                observed = supervisor.inspect(owned)
                assert answer["kind"] == "pong" and observed["verified"]
            finally:
                if not prestarted:
                    self.proofs.append(supervisor.terminate_tree(owned))
            return InvocationObservation(
                invocation_id=invocation.invocation_id,
                dispatch_id=invocation.dispatch_id,
                runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
                native_dispatch_ref=observed["unit"],
                native_ack_ref="fixture-pong:" + str(answer["pid"]),
            )

    return NoModelSystemdDriver()


def test_actual_pg_sqlite_single_run_replay_and_readback(setup, tmp_path):
    host, _, _, _ = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    result = host.handle(request)
    assert result.status == "delivered"
    assert result.attempt_id and result.dispatch_id
    assert {receipt["layer"] for receipt in result.pg_receipts} >= {
        "accepted_by_authority",
        "target_inbox_committed",
        "runtime_dispatched",
        "runtime_acknowledged",
        "response_received",
    }
    assert {receipt["layer"] for receipt in result.node_receipts} >= {
        "target_inbox_committed",
        "runtime_dispatched",
        "runtime_acknowledged",
    }
    assert host.handle(request) == result
    assert host.handle(request.model_copy(update={"action": "readback"})) == result
    assert setup.driver.calls == [request.operation_id]
    assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(1,)]
    assert query(setup, "SELECT count(*) FROM inbox_messages") == [(1,)]


def test_second_authorized_operation_cannot_consume_same_run(setup, tmp_path):
    host, _, _, _ = _host(setup, tmp_path)
    first = _send(setup, host.policy)
    second = _send(setup, host.policy)
    assert host.handle(first).status == "delivered"
    with pytest.raises(HostNodeRejected, match="already bound"):
        host.handle(second)
    assert setup.driver.calls == [first.operation_id]
    assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(1,)]


def test_readback_after_host_deadline_and_artifact_cleanup_is_read_only(setup, tmp_path):
    host, native, config, _ = _host(setup, tmp_path, deadline_seconds=2)
    request = _send(setup, host.policy)
    first = host.handle(request)
    assert first.status == "delivered"
    native.unlink()
    config.unlink()
    time.sleep(2.1)
    with pytest.raises(HostNodeRejected, match="deadline"):
        host.handle(request)
    assert host.handle(request.model_copy(update={"action": "readback"})) == first
    assert setup.driver.calls == [request.operation_id]


def test_host_restart_replays_same_operation_and_rejects_changed_policy(setup, tmp_path):
    host, native, config, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    first = host.handle(request)
    replacement = CodexHostNodeEndpoint(
        host.policy,
        setup.dispatcher,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    assert replacement.handle(request) == first
    assert setup.driver.calls == [request.operation_id]
    changed = host.policy.model_copy(
        update={"deadline": host.policy.deadline + timedelta(seconds=1)}
    )
    changed_host = CodexHostNodeEndpoint(
        changed,
        setup.dispatcher,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    with pytest.raises(HostNodeRejected, match="already bound"):
        changed_host.handle(request)
    assert setup.driver.calls == [request.operation_id]


def test_socket_ack_loss_then_exact_readback_never_reinvokes(setup, tmp_path):
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    server = CodexHostUnixServer(host, private / "ack-loss.sock")
    errors = []

    def serve():
        try:
            server.serve_one()
        except OSError as error:
            errors.append(type(error).__name__)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(server.socket_path))
            client.sendall(request.model_dump_json().encode() + b"\n")
            client.shutdown(socket.SHUT_RDWR)
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert errors in ([], ["BrokenPipeError"])
        result = host.handle(request.model_copy(update={"action": "readback"}))
        assert result.status == "delivered"
        assert host.handle(request).status == "delivered"
        assert setup.driver.calls == [request.operation_id]
        assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(1,)]
    finally:
        server.close()


def test_two_host_instances_racing_same_run_invoke_once(setup, tmp_path):
    host, native, config, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    second = CodexHostNodeEndpoint(
        host.policy,
        setup.dispatcher,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(endpoint.handle, request) for endpoint in (host, second)]
        results = [future.result(timeout=15) for future in futures]
    assert {result.status for result in results} <= {"delivered", "delivering", "queued"}
    assert host.handle(request.model_copy(update={"action": "readback"})).status == "delivered"
    assert setup.driver.calls == [request.operation_id]
    assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(1,)]


def test_host_interrupted_after_pg_prepare_resumes_same_attempt(setup, tmp_path):
    host, native, config, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)

    def interrupted(_identity):
        raise SystemExit(83)

    host.dispatcher.after_claim = interrupted
    with pytest.raises(SystemExit) as caught:
        host.handle(request)
    assert caught.value.code == 83
    prepared = query(
        setup,
        "SELECT attempt_id,status FROM delivery_attempts WHERE message_id=%s",
        (request.message_id,),
    )
    assert len(prepared) == 1 and prepared[0][1] == "prepared"
    assert setup.driver.calls == []
    replacement = CodexHostNodeEndpoint(
        host.policy,
        DeliveryDispatcher(setup.service),
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    assert replacement.handle(request).status == "delivered"
    assert query(
        setup,
        "SELECT attempt_id FROM delivery_attempts WHERE message_id=%s",
        (request.message_id,),
    ) == [(prepared[0][0],)]
    assert setup.driver.calls == [request.operation_id]


def test_post_dispatch_uncertain_replay_never_reinvokes(setup, tmp_path):
    host, native, config, private = _host(setup, tmp_path)
    setup.driver.fail = True
    request = _send(setup, host.policy)
    assert host.handle(request).status == "uncertain"
    replacement = CodexHostNodeEndpoint(
        host.policy,
        DeliveryDispatcher(setup.service),
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    assert replacement.handle(request).status == "uncertain"
    assert setup.driver.calls == [request.operation_id]
    assert query(
        setup,
        "SELECT count(*) FROM delivery_receipts WHERE layer='runtime_dispatched'",
    ) == [(1,)]


def test_wrong_run_digest_correlation_and_revoked_grant_are_pre_call(setup, tmp_path):
    host, native, _, _ = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    with pytest.raises(HostNodeRejected, match="host-pinned"):
        host.handle(request.model_copy(update={"native_sha256": "f" * 64}))
    wrong_correlation = _send(setup, host.policy, changed_run="other-run-" + uuid.uuid4().hex)
    with pytest.raises(HostNodeRejected, match="committed command"):
        host.handle(wrong_correlation)
    native.chmod(0o700)
    with pytest.raises(HostNodeRejected, match="identity or mode"):
        host.handle(request)
    native.chmod(0o500)
    query(
        setup,
        "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
        (setup.authority.context.grant_ref,),
    )
    spawn = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    with pytest.raises(HostNodeRejected, match="Grant"):
        host.start_native(request, spawn)
    assert host.handle(request).status == "blocked"
    assert setup.driver.calls == []
    assert query(
        setup, "SELECT count(*) FROM delivery_receipts WHERE layer='runtime_dispatched'"
    ) == [(0,)]


def test_socket_exact_schema_same_uid_and_no_command_surface(setup, tmp_path):
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    server = CodexHostUnixServer(host, private / "host.sock")
    errors = []

    def serve():
        try:
            server.serve_one()
        except Exception as error:  # noqa: BLE001 -- surface result is asserted below
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(server.socket_path))
            client.sendall(request.model_dump_json().encode() + b"\n")
            reply = client.recv(server.MAX_RESPONSE)
        thread.join(timeout=15)
        assert not thread.is_alive() and errors == []
        assert json.loads(reply)["status"] == "delivered"
        assert setup.driver.calls == [request.operation_id]
        with pytest.raises(ValueError):
            CodexHostRequest.model_validate(
                {**request.model_dump(), "argv": ["systemd-run", "sleep"]}
            )
    finally:
        server.close()
    assert not server.socket_path.exists()


def test_malformed_guest_request_is_rejected_and_host_serves_valid_followup(setup, tmp_path):
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    server = CodexHostUnixServer(host, private / "malformed.sock")
    try:
        for body, expected in (
            ({**request.model_dump(mode="json"), "argv": ["systemd-run", "sleep"]}, "rejected"),
            (request.model_dump(mode="json"), "delivered"),
        ):
            thread = threading.Thread(target=server.serve_one)
            thread.start()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(server.socket_path))
                client.sendall(json.dumps(body).encode() + b"\n")
                response = client.recv(server.MAX_RESPONSE)
            thread.join(timeout=15)
            assert not thread.is_alive()
            assert json.loads(response).get("state", json.loads(response).get("status")) == expected
        assert setup.driver.calls == [request.operation_id]
    finally:
        server.close()


def test_real_host_systemd_no_model_through_narrow_socket(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("real non-root Linux user manager is required")
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )

    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    server = CodexHostUnixServer(host, private / "systemd.sock")
    errors = []

    def serve():
        try:
            server.serve_one()
        except Exception as error:  # noqa: BLE001 -- retained for assertion
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(server.socket_path))
            client.sendall(request.model_dump_json().encode() + b"\n")
            reply = client.recv(server.MAX_RESPONSE)
        thread.join(timeout=20)
        assert not thread.is_alive() and errors == []
        result = json.loads(reply)
        assert result["status"] == "delivered"
        assert driver.calls == [request.operation_id]
        assert len(driver.proofs) == 1
        assert driver.proofs[0]["verified"] and driver.proofs[0]["remaining_pids"] == []
        assert host.policy.run_id in driver.proofs[0]["unit"]
        assert (
            list((Path(f"/run/user/{os.geteuid()}") / "acs-systemd-supervisor-env").glob("*.conf"))
            == []
        )
    finally:
        server.close()
        supervisor.close()


def test_bwrap_guest_only_sees_fixed_host_socket(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("non-root Linux sandbox is required")
    helper = Path("/opt/acs/codex-sandbox/bin/bwrap")
    if not helper.is_file():
        pytest.skip("reviewed bubblewrap helper is unavailable")
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )
    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    boot_operation = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    assert host.start_native(request, boot_operation)["verified"]
    with pytest.raises(HostNodeRejected, match="already attempted"):
        host.start_native(request, boot_operation)
    server = CodexHostUnixServer(host, private / "sandbox.sock")
    errors = []

    def serve():
        try:
            server.serve_one()
        except Exception as error:  # noqa: BLE001 -- retained for assertion
            errors.append(error)

    guest_code = (
        "import json,os,socket,sys;"
        "assert not os.path.exists('/run/user/%s/bus'%os.getuid());"
        "assert os.listdir('/home') == [];"
        "s=socket.socket(socket.AF_UNIX);s.connect('/run/acs/host.sock');"
        "s.sendall(sys.stdin.buffer.read());"
        "sys.stdout.buffer.write(s.recv(262144))"
    )
    thread = threading.Thread(target=serve)
    thread.start()
    try:
        completed = subprocess.run(
            [
                str(helper),
                "--ro-bind",
                "/",
                "/",
                "--tmpfs",
                "/home",
                "--tmpfs",
                "/root",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/opt",
                "--tmpfs",
                "/run",
                "--dir",
                "/run/acs",
                "--ro-bind",
                str(server.socket_path),
                "/run/acs/host.sock",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--unshare-user",
                "--unshare-pid",
                "--unshare-uts",
                "--unshare-ipc",
                "--share-net",
                "--die-with-parent",
                "--new-session",
                "--",
                "/usr/bin/python3",
                "-c",
                guest_code,
            ],
            input=request.model_dump_json().encode() + b"\n",
            capture_output=True,
            timeout=15,
            check=False,
        )
        thread.join(timeout=15)
        assert completed.returncode == 0, completed.stderr.decode()[-1000:]
        assert not thread.is_alive() and errors == []
        assert json.loads(completed.stdout)["status"] == "delivered"
        assert driver.calls == [request.operation_id]
        assert json.loads(completed.stdout)["os_observation"]["verified"]
        assert host.inspect_native()["remaining_pids"]
        stopped = host.stop_native()
        assert stopped["verified"] and stopped["remaining_pids"] == []
        assert host.policy.run_id in stopped["unit"]
        assert (
            host.handle(request.model_copy(update={"action": "readback"})).os_observation == stopped
        )
    finally:
        server.close()
        supervisor.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "permission_removed",
        "scope_revoked",
        "authority_revoked",
        "slot_revoked",
        "policy_changed",
    ],
)
def test_spawn_current_authority_fence_rejects_without_systemd_or_node_effect(
    setup,
    tmp_path,
    mutation,
):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("non-root Linux user manager is required")
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )
    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    spawn = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    changes = {
        "permission_removed": (
            "UPDATE grants SET permissions=%s WHERE grant_ref=%s",
            (json.dumps(["message.read"]), setup.authority.context.grant_ref),
        ),
        "scope_revoked": (
            "UPDATE scopes SET status='revoked' WHERE scope_id='local-scope'",
            (),
        ),
        "authority_revoked": (
            "UPDATE authority_instances SET status='revoked' WHERE authority_id=%s",
            (setup.authority.context.authority_id,),
        ),
        "slot_revoked": (
            "UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'",
            (),
        ),
        "policy_changed": (
            "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
            (json.dumps({"version": "changed"}),),
        ),
    }
    statement, values = changes[mutation]
    query(setup, statement, values)
    try:
        with pytest.raises(HostNodeRejected):
            host.start_native(request, spawn)
        assert driver.owned is None and driver.calls == [] and driver.proofs == []
        assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(0,)]
        assert setup.journal.receipts(request.operation_id) == ()
        units = subprocess.run(
            [
                "/usr/bin/systemctl",
                "--user",
                "list-units",
                "--all",
                "--plain",
                "--no-legend",
                f"acs-{host.policy.run_id}-*.service",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert units.returncode == 0 and units.stdout.strip() == ""
        with sqlite3.connect(private / "runs.sqlite") as connection:
            assert connection.execute("SELECT count(*) FROM codex_host_boot").fetchone() == (0,)
    finally:
        supervisor.close()


def test_spawn_holds_grant_row_until_systemd_birth_is_observed(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("non-root Linux user manager is required")
    host, _, _, _ = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )
    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    entered = threading.Event()
    release = threading.Event()
    original_spawn = driver.spawn

    def held_spawn(operation):
        original_spawn(operation)
        entered.set()
        assert release.wait(timeout=5)

    driver.spawn = held_spawn
    operation = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        launch = pool.submit(host.start_native, request, operation)
        assert entered.wait(timeout=5)
        revoke = pool.submit(
            query,
            setup,
            "UPDATE grants SET permissions=%s WHERE grant_ref=%s",
            (json.dumps(["message.read"]), setup.authority.context.grant_ref),
        )
        try:
            time.sleep(0.2)
            assert not revoke.done(), "Grant changed while host Systemd spawn fence was held"
        finally:
            release.set()
        assert launch.result(timeout=10)["verified"]
        revoke.result(timeout=10)
    try:
        assert host.handle(request).status == "blocked"
        assert driver.calls == []
        assert host.stop_native()["remaining_pids"] == []
    finally:
        supervisor.close()


def test_spawn_final_deadline_after_birth_stops_unit_without_node_effect(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("non-root Linux user manager is required")
    host, _, _, private = _host(setup, tmp_path, deadline_seconds=2)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )
    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    original_spawn = driver.spawn

    def delayed_spawn(operation):
        original_spawn(operation)
        time.sleep(2.1)

    driver.spawn = delayed_spawn
    operation = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    try:
        with pytest.raises(HostNodeRejected, match="final authority deadline"):
            host.start_native(request, operation)
        assert driver.owned is not None
        assert supervisor.inspect(driver.owned)["remaining_pids"] == []
        assert driver.calls == []
        assert setup.journal.receipts(request.operation_id) == ()
        assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(0,)]
        with sqlite3.connect(private / "runs.sqlite") as connection:
            assert connection.execute("SELECT state FROM codex_host_boot").fetchone() == ("intent",)
    finally:
        supervisor.close()


@pytest.mark.parametrize("through_temporal", [False, True])
def test_production_codex_driver_path_with_real_systemd_and_no_model(
    setup,
    tmp_path,
    through_temporal,
):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("non-root Linux user manager is required")
    if through_temporal and (
        os.environ.get("ACS_P1_TEMPORAL_ENDPOINT") != "127.0.0.1:7239"
        or not os.environ.get("ACS_P1_TEMPORAL_NAMESPACE")
    ):
        pytest.skip("real local Temporal namespace is required")
    private = tmp_path / "codex-host"
    private.mkdir(mode=0o700)
    native = private / "codex"
    native.write_bytes((Path(__file__).parent / "p1_codex_stdio_fixture.py").read_bytes())
    native.chmod(0o500)
    codex_home = private / "codex-home"
    codex_home.mkdir(mode=0o700)
    config = codex_home / "config.toml"
    config.write_text('default_permissions="test-profile"\napproval_policy="never"\n')
    config.chmod(0o600)
    schema = private / "schema.json"
    schema.write_bytes(b'{"fixture":true}\n')
    schema.chmod(0o600)
    policy = CodexHostRunPolicy(
        run_id="p1-codex-" + uuid.uuid4().hex,
        tenant_id=setup.authority.tenant_id,
        authority_id=setup.authority.context.authority_id,
        authority_incarnation=setup.authority.context.authority_incarnation,
        scope_id="local-scope",
        agent_slot_id="local-slot",
        scope_policy_sha256=_scope_policy_hash(setup),
        endpoint_id="endpoint",
        source_commit="a" * 40,
        native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        deadline=datetime.now(UTC) + timedelta(seconds=60),
    )
    setup.authority.create_work_item(
        command(setup.authority, "work_item.create", "work-p1"),
        "local-scope",
        "local-slot",
        policy.source_commit,
    )
    binding = BindingIdentity(
        setup.journal.node_id,
        setup.journal.boot_incarnation,
        "p1-codex-runtime",
        "p1-codex-execution",
        "local-slot",
        2,
    )
    profile = LaunchProfile(
        str(native),
        policy.native_sha256,
        "0.153.2",
        str(schema),
        hashlib.sha256(schema.read_bytes()).hexdigest(),
        str(private),
        str(codex_home),
        policy.config_sha256,
        "test-profile",
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )

    def current(operation, observed_binding):
        assert observed_binding == binding
        assert operation.grant_ref == setup.authority.context.grant_ref
        assert operation.deadline <= policy.deadline
        rows = query(
            setup,
            "SELECT revoked_at,expires_at FROM grants WHERE grant_ref=%s",
            (operation.grant_ref,),
        )
        assert len(rows) == 1 and rows[0][0] is None and rows[0][1] > datetime.now(UTC)
        if operation.operation_id != policy.run_id + "-spawn":
            assert operation.operation_id.startswith("delivery-invocation:")
            attempt_id = operation.operation_id.removeprefix("delivery-invocation:")
            attempt = query(
                setup,
                "SELECT m.command_id,m.message_id FROM delivery_attempts a "
                "JOIN delivery_messages m ON m.tenant_id=a.tenant_id "
                "AND m.message_id=a.message_id WHERE a.attempt_id=%s",
                (attempt_id,),
            )
            assert attempt == [(operation.command_id, operation.message_id)]

    driver = CodexAppServerDriver(
        policy.run_id + "-binding",
        profile,
        DriverJournal(private / "driver.sqlite"),
        identity=binding,
        check_current=current,
        supervisor=supervisor,
        rpc_timeout=5,
    )

    def authorize(invocation, observed_binding):
        assert observed_binding == binding
        return AuthorizedOperation(
            invocation.invocation_id,
            invocation.command_id,
            invocation.message_id,
            invocation.envelope.grant_ref,
            invocation.envelope.packet.deadline,
        )

    setup.endpoint.driver = NativeDeliveryAdapter(driver, authorize_invocation=authorize)
    setup.service.bind_endpoint(
        command(setup.authority, "message.bind", "endpoint", revision=1),
        EndpointBindingRequest(
            scope_id="local-scope",
            agent_slot_id="local-slot",
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        ),
    )
    temporal = None
    if through_temporal:
        temporal = TemporalHostDispatcher(
            setup.dispatcher,
            endpoint="127.0.0.1:7239",
            namespace=os.environ["ACS_P1_TEMPORAL_NAMESPACE"],
            task_queue="p1-host-" + policy.run_id,
            deadline=policy.deadline,
        )
    host = CodexHostNodeEndpoint(
        policy,
        temporal or setup.dispatcher,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
    )
    request = _send(setup, policy, binding_revision=2)
    spawn = AuthorizedOperation(
        policy.run_id + "-spawn",
        policy.run_id + "-command-spawn",
        policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        policy.deadline,
    )
    try:
        if through_temporal:
            budget = private / "fixture-budget.json"
            budget.write_text(
                json.dumps(
                    {
                        "schema_version": "acs-p1-model-request-budget/1",
                        "decision_id": DECISION_ID,
                        "source_commit": policy.source_commit,
                        "source_tree": "b" * 40,
                        "scene_profile_sha256": "c" * 64,
                        "scenario_id": "P1-CODEX-LIFECYCLE",
                        "provider_alias": "fixture-provider",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "low",
                        "prompt": MODEL_PROMPT,
                        "max_turn_starts": 1,
                        "max_collect_reads": 6,
                        "max_elapsed_seconds": 120,
                        "retry_policy": "No second turn/start after uncertainty.",
                        "spend_status": "Provider monetary cap not observed; cost unknown.",
                        "tool_policy": "No tool invocation or delegation.",
                    }
                ),
                encoding="utf-8",
            )
            budget.chmod(0o600)
            scene = CodexHostSceneService(
                host,
                setup.journal,
                driver,
                setup.endpoint.driver,
                temporal,
                source_tree="b" * 40,
                scene_sha256="c" * 64,
                budget_path=budget,
                budget_sha256=hashlib.sha256(budget.read_bytes()).hexdigest(),
                artifact_root=private / "artifacts",
                environment_dir=Path(f"/run/user/{os.geteuid()}") / "acs-systemd-supervisor-env",
                provider_alias="fixture-provider",
                model="gpt-5.6-sol",
            )
            result = scene.handle(request)
            assert result.status == "delivered" and result.scene_readback
            assert result.scene_readback["temporal"]["run_id"] == temporal.last["provider_run_id"]
            assert result.scene_readback["response"]["disposition"] == "applied"
            assert result.scene_readback["os"]["remaining_pids"] == []
            assert scene.handle(request.model_copy(update={"action": "readback"})) == result
            assert scene.handle(request).scene_readback_sha256 == result.scene_readback_sha256
            with driver.journal._connect() as connection:
                starts = connection.execute(
                    "SELECT count(*) FROM driver_events WHERE kind='rpc_dispatch' "
                    "AND body LIKE '%turn/start%'"
                ).fetchone()[0]
            assert starts == 1
            return
        boot = host.start_native(request, spawn)
        assert boot["verified"] and policy.run_id in boot["unit"]
        result = host.handle(request)
        assert result.status == "delivered", query(
            setup,
            "SELECT state,last_error FROM delivery_messages WHERE message_id=%s",
            (request.message_id,),
        )
        assert result.os_observation and result.os_observation["verified"]
        dispatch = {
            "authority": setup.authority,
            "service": setup.service,
            "endpoint": setup.endpoint,
            "adapter": setup.endpoint.driver,
            "identity": {
                "tenant_id": request.tenant_id,
                "message_id": request.message_id,
                "operation_id": request.operation_id,
            },
            "attempt_id": result.attempt_id,
            "invocation_id": "delivery-invocation:" + result.attempt_id,
            "dispatch_id": result.dispatch_id,
        }
        projection = project_original_terminal(
            dispatch,
            setup.journal,
            driver,
            private / "artifacts",
            pause=lambda _seconds: None,
        )
        assert projection["disposition"] == "applied"
        assert query(
            setup,
            "SELECT count(*) FROM native_response_observations WHERE invocation_id=%s",
            (dispatch["invocation_id"],),
        ) == [(1,)]
        assert query(
            setup,
            "SELECT count(*) FROM delivery_receipts "
            "WHERE message_id=%s AND layer='response_received'",
            (request.message_id,),
        ) == [(1,)]
        with driver.journal._connect() as connection:
            rows = connection.execute(
                "SELECT body FROM driver_events WHERE kind='rpc_dispatch'"
            ).fetchall()
        assert sum(json.loads(row[0]).get("method") == "turn/start" for row in rows) == 1
        assert host.handle(request).status == "delivered"
        with driver.journal._connect() as connection:
            rows = connection.execute(
                "SELECT body FROM driver_events WHERE kind='rpc_dispatch'"
            ).fetchall()
        assert sum(json.loads(row[0]).get("method") == "turn/start" for row in rows) == 1
        stopped = host.stop_native()
        assert stopped["verified"] and stopped["remaining_pids"] == []
        assert (
            host.handle(request.model_copy(update={"action": "readback"})).os_observation == stopped
        )
    finally:
        supervisor.close()
        driver.detach_transport()


def test_windows_fails_closed_before_artifact_or_socket_access(tmp_path):
    if os.name == "posix":
        pytest.skip("Windows-specific fail-closed boundary")
    policy = CodexHostRunPolicy(
        run_id="p1-codex-windows",
        tenant_id="tenant",
        authority_id="authority",
        authority_incarnation="incarnation",
        scope_id="scope",
        agent_slot_id="slot",
        scope_policy_sha256=hashlib.sha256(b"{}").hexdigest(),
        endpoint_id="endpoint",
        source_commit="a" * 40,
        native_sha256="b" * 64,
        config_sha256="c" * 64,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )
    private = tmp_path / "host"
    private.mkdir()
    with pytest.raises(HostNodeRejected, match="non-root POSIX"):
        CodexHostNodeEndpoint(
            policy,
            object(),
            private / "runs.sqlite",
            native_path=private / "codex",
            config_path=private / "config",
        )

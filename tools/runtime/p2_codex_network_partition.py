"""Execute a bounded P2 tunnel partition after the durable dispatch marker."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nacl.signing import SigningKey
from psycopg.conninfo import make_conninfo

from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.domain import DomainAuthority
from runtime.receiver_crypto import public_key, sha256, tls_fingerprint, verify
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime.operator_files import OperatorFileError
from tools.runtime.p2_control_proof import issue as issue_control_challenge
from tools.runtime.p2_control_proof import validate as validate_control_proof
from tools.runtime.p2_codex_half_loop import _command, _json, _write


def _listening(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex((host, port)) == 0


def _wait(host: str, port: int, expected: bool, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _listening(host, port) is expected:
            return
        time.sleep(0.05)
    raise RuntimeError("reverse tunnel port did not reach expected state")


class RelayPartition:
    def __init__(self, arguments):
        self.arguments = arguments
        self.events = []
        self.old_pid = None
        self.old_birth = None
        self.process = None
        self.signed_dispatch_sha256 = None
        self.supervisor = SystemdUserSupervisor(
            tasks_max=32, memory_max=268_435_456, cpu_quota_percent=50,
            termination_timeout=10,
        )

    def _snapshot(self, phase: str, pid: int | None) -> dict:
        value = {
            "phase": phase,
            "observed_at": datetime.now(UTC).isoformat(),
            "listener_pid": pid,
            "worker_port_listening": _listening(self.arguments.relay_host, self.arguments.worker_port),
            "client_port_listening": _listening(self.arguments.relay_host, self.arguments.client_port),
            "control_process_chain": self._control_chain(),
        }
        self.events.append(value)
        return value

    @staticmethod
    def _control_chain() -> list[dict]:
        result = []
        pid = os.getpid()
        for _ in range(12):
            stat = Path(f"/proc/{pid}/stat")
            command = Path(f"/proc/{pid}/cmdline")
            if not stat.is_file() or not command.is_file():
                break
            fields = stat.read_text(encoding="ascii").split()
            result.append({
                "pid": pid, "birth": fields[21],
                "argv_sha256": hashlib.sha256(command.read_bytes()).hexdigest(),
            })
            parent = int(fields[3])
            if parent <= 1 or parent == pid:
                break
            pid = parent
        return result

    @staticmethod
    def _birth(pid: int) -> str:
        return Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()[21]

    def _start(self):
        if self.process is not None and self.process.process.poll() is None:
            return self.process
        command = [
            str(self.arguments.runtime_python), str(self.arguments.tunnel_script), "listen",
            "--host", self.arguments.relay_host, "--worker-port", str(self.arguments.worker_port),
            "--client-port", str(self.arguments.client_port), "--token",
            str(self.arguments.token),
        ]
        self.process = self.supervisor.launch(
            command, cwd=str(self.arguments.tunnel_script.parent),
            env={
                "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                "PYTHONPATH": self.arguments.runtime_pythonpath,
            },
            label="p2-network-relay",
        )
        self.arguments.relay_pid_file.write_text(str(self.process.process.pid))
        _wait(self.arguments.relay_host, self.arguments.worker_port, True)
        _wait(self.arguments.relay_host, self.arguments.client_port, True)
        self._wait_tls()
        return self.process

    def _wait_tls(self) -> None:
        import ssl

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        deadline = time.monotonic() + self.arguments.worker_reconnect_seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    (self.arguments.relay_host, self.arguments.client_port), timeout=10,
                ) as raw, context.wrap_socket(raw, server_hostname="receiver") as tls:
                    observed = tls_fingerprint(tls.getpeercert(binary_form=True))
                if observed != self.arguments.expected_tls_fingerprint:
                    raise RuntimeError("tunnel TLS fingerprint differs")
                return
            except (OSError, TimeoutError, ssl.SSLError, RuntimeError) as error:
                last_error = type(error).__name__
                time.sleep(0.2)
        raise RuntimeError("reverse tunnel worker TLS readiness failed: " + str(last_error))

    def start(self) -> None:
        process = self._start()
        proof = self.supervisor.inspect(process)
        start = self._snapshot("initial", process.process.pid)
        start["containment"] = proof
        start["listener_birth"] = process.birth_ref

    def _control_probe(self) -> dict:
        if self.arguments.control_challenge.exists() or self.arguments.control_proof.exists():
            raise RuntimeError("control proof run paths are not fresh")
        challenge = issue_control_challenge(
            self.arguments.control_challenge, run_id=self.arguments.suffix,
            expected_host=self.arguments.control_host,
            expected_session=self.arguments.control_session,
            ttl_seconds=int(self.arguments.control_timeout_seconds),
        )
        deadline = time.monotonic() + self.arguments.control_timeout_seconds
        while time.monotonic() < deadline:
            try:
                result = validate_control_proof(
                    self.arguments.control_challenge, self.arguments.control_proof,
                    expected_public_key=self.arguments.control_public_key,
                    expected_host=self.arguments.control_host,
                    expected_session=self.arguments.control_session,
                )
                result["nonce_sha256"] = hashlib.sha256(challenge["nonce"].encode()).hexdigest()
                return result
            except (FileNotFoundError, OperatorFileError, ValueError):
                pass
            time.sleep(0.1)
        raise RuntimeError("independent SSH control proof was not received")

    def __call__(self, invocation, signed_dispatch) -> None:
        verify(
            self.arguments.control_authority_public_key,
            signed_dispatch.signature, signed_dispatch.admission,
        )
        self.signed_dispatch_sha256 = sha256(signed_dispatch)
        if self.process is None or self.process.process.poll() is not None:
            raise RuntimeError("owned reverse tunnel process is unavailable")
        pid = self.process.process.pid
        self.old_pid = pid
        self.old_birth = self._birth(pid)
        before = self._snapshot("before_partition", pid)
        before["listener_birth"] = self.old_birth
        if not before["worker_port_listening"] or not before["client_port_listening"]:
            raise RuntimeError("reverse tunnel was not healthy before partition")
        if self._birth(pid) != self.old_birth:
            raise RuntimeError("reverse tunnel PID birth changed before signal")
        stopped = self.supervisor.terminate_tree(self.process)
        _wait(self.arguments.relay_host, self.arguments.worker_port, False)
        _wait(self.arguments.relay_host, self.arguments.client_port, False)
        during = self._snapshot("partitioned", None)
        during["old_relay_termination"] = stopped
        if during["worker_port_listening"] or during["client_port_listening"]:
            raise RuntimeError("reverse tunnel partition did not isolate the route")
        during["control_probe"] = self._control_probe()
        time.sleep(self.arguments.partition_seconds)

    def restore(self, invocation) -> None:
        process = self._start()
        after = self._snapshot("restored", process.process.pid)
        after["listener_birth"] = process.birth_ref
        after["containment"] = self.supervisor.inspect(process)
        after["logical_message_id"] = invocation.message_id
        after["operation_id"] = invocation.operation_id
        after["attempt_id"] = invocation.attempt_id
        after["dispatch_id"] = invocation.dispatch_id

    def finish(self) -> dict:
        process = self._start()
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((self.arguments.relay_host, self.arguments.client_port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname="receiver") as tls:
                observed_tls = tls_fingerprint(tls.getpeercert(binary_form=True))
        proof = {
            "pid": process.process.pid, "birth": process.birth_ref,
            "healthy": process.process.poll() is None,
            "worker_port_listening": _listening(self.arguments.relay_host, self.arguments.worker_port),
            "client_port_listening": _listening(self.arguments.relay_host, self.arguments.client_port),
            "containment": self.supervisor.inspect(process),
            "tls_certificate_sha256": observed_tls,
            "tls_verified": observed_tls == self.arguments.expected_tls_fingerprint,
        }
        if not proof["tls_verified"]:
            raise RuntimeError("restored tunnel TLS fingerprint differs")
        return proof

    def close(self) -> dict:
        termination = None
        if self.process is not None:
            try:
                termination = self.supervisor.terminate_tree(self.process)
            except Exception as error:
                termination = {"verified": False, "error_type": type(error).__name__}
        self.supervisor.close()
        return {"termination": termination, "closed": True}


def execute(arguments) -> int:
    state = _json(arguments.state)
    if arguments.expected_tls_fingerprint != state["tls_certificate_sha256"]:
        raise RuntimeError("expected TLS fingerprint differs from committed endpoint state")
    base = _json(arguments.profile)["postgres_dsn"]
    dsn = make_conninfo(base, options=f"-c search_path={state['schema_name']} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    signing = SigningKey(bytes.fromhex(arguments.authority_seed.read_text().strip()))
    partition = RelayPartition(arguments)
    arguments.control_authority_public_key = public_key(signing)
    endpoint = service = queued = identity = None
    sentinel = message_id = None
    fault_result = None
    recovery_result = None
    authenticated_readback = None
    recovery_route = None
    relay_close = None
    try:
        partition.start()
        endpoint = RemoteNodeEndpointAdapter(
            authority, state["endpoint_id"],
            RemoteSenderDeployment(
                authority_signing_key=signing,
                expected_boot_incarnation=state["boot_incarnation"], journal_generation=1,
            ),
            timeout=10, after_dispatch_mark=partition,
        )
        service = DeliveryService(authority, {state["endpoint_id"]: endpoint})
        service.bind_endpoint(
            _command(authority, "message.bind", "message", state["endpoint_id"]),
            EndpointBindingRequest(
                scope_id="local-scope", agent_slot_id="local-slot",
                expires_at=datetime.now(UTC) + timedelta(minutes=20),
            ),
        )
        work_id = "p2-network-work-" + arguments.suffix
        authority.create_work_item(
            _command(authority, "work_item.create", "work_item", work_id),
            "local-scope", "local-slot", state["source_commit"],
        )
        sentinel = "P2-CODEX-NETWORK-PARTITION-" + arguments.suffix
        message_id = "p2-network-message-" + arguments.suffix
        packet = DeliveryPacket(
            work_item_id=work_id, target_scope_id="local-scope",
            target_agent_slot_id="local-slot", accepted_revision=0,
            goal="Recover one P2 Codex delivery across a bounded Runtime tunnel partition",
            accepted_state_summary="P1 passed; P2 remains blocked pending all scenarios",
            request="Return exactly this sentinel and no other text: " + sentinel
                    + ". Do not call tools and do not delegate.",
            constraints=("one native Codex turn", "no delegation", "no tool calls"),
            source_baseline=state["source_commit"],
            context_digests=(state["source_tree"].ljust(64, "0")[:64],),
            expected_response=sentinel,
            required_evidence=("PostgreSQL", "receiver SQLite", "Driver journal", "Node outbox"),
            activation="invoke", deadline=datetime.now(UTC) + timedelta(minutes=5),
            maximum_attempts=1, retry_delay_seconds=1,
        )
        queued = service.send_message(
            _command(authority, "message.send", "message", message_id), packet,
            endpoint_id=state["endpoint_id"], binding_revision=1,
        )
        identity = {
            "tenant_id": authority.tenant_id, "message_id": message_id,
            "operation_id": queued.operation_id,
        }
        fault_result = DeliveryDispatcher(
            service, worker_id="linux-p2-network-sender",
        ).dispatch(identity)
        if fault_result.get("status") != "uncertain":
            raise RuntimeError("partitioned dispatch did not enter uncertain")
        dispatch = endpoint.store.dispatch_admission(queued.operation_id)
        if dispatch is None:
            raise RuntimeError("partitioned dispatch admission was not persisted")
        if sha256(dispatch) != partition.signed_dispatch_sha256:
            raise RuntimeError("persisted signed dispatch changed after fault")
        partition.restore(dispatch.admission)
        recovery_result = DeliveryDispatcher(
            service, worker_id="linux-p2-network-reconciler",
        ).reconcile_marked(identity)
        authenticated_readback = endpoint.inspect_delivery(
            queued.operation_id, "uncertain",
        )
    finally:
        try:
            if partition.signed_dispatch_sha256 is not None:
                recovery_route = partition.finish()
        finally:
            relay_close = partition.close()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with authority._connect() as connection:
            row = connection.execute(
                "SELECT state,receipt_high_water FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
                (authority.tenant_id, message_id),
            ).fetchone()
        if row and row[1] == "response_received":
            break
        time.sleep(1)
    with authority._connect() as connection:
        message = connection.execute(
            "SELECT state,receipt_high_water,attempts,activation_node_id,activation_machine_id "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
            (authority.tenant_id, message_id),
        ).fetchone()
        receipts = connection.execute(
            "SELECT layer,receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s ORDER BY observed_at",
            (authority.tenant_id, message_id),
        ).fetchall()
        attempt = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts WHERE tenant_id=%s AND message_id=%s",
            (authority.tenant_id, message_id),
        ).fetchone()
    evidence = {
        "schema_version": "acs-p2-network-partition-evidence/1",
        "scenario_id": "P2-CODEX-NETWORK-PARTITION",
        "status": "blocked",
        "reason": "scenario evidence only; formal Gate review pending",
        "source_commit": state["source_commit"], "source_tree": state["source_tree"],
        "message_id": message_id, "operation_id": queued.operation_id,
        "attempt": list(attempt) if attempt else None,
        "message": list(message) if message else None,
        "receipts": [list(value) for value in receipts],
        "fault_result": fault_result, "recovery_result": recovery_result,
        "authenticated_readback": authenticated_readback,
        "partition_events": partition.events,
        "signed_dispatch_sha256": partition.signed_dispatch_sha256,
        "runtime_transport": "end-to-end TLS through Runtime reverse TCP tunnel",
        "control_transport": "SSH retained only for deployment and evidence control",
        "expected_sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
        "recovery_route": recovery_route,
        "relay_close": relay_close,
    }
    _write(arguments.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if message and message[1] == "response_received" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--authority-seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--tunnel-script", type=Path, required=True)
    parser.add_argument("--token", type=Path, required=True)
    parser.add_argument("--relay-pid-file", type=Path, required=True)
    parser.add_argument("--relay-log", type=Path, required=True)
    parser.add_argument("--worker-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--relay-host", required=True)
    parser.add_argument("--partition-seconds", type=float, default=1.0)
    parser.add_argument("--worker-reconnect-seconds", type=float, default=2.0)
    parser.add_argument("--control-challenge", type=Path, required=True)
    parser.add_argument("--control-proof", type=Path, required=True)
    parser.add_argument("--control-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--control-public-key", required=True)
    parser.add_argument("--control-host", required=True)
    parser.add_argument("--control-session", required=True)
    parser.add_argument("--expected-tls-fingerprint", required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-pythonpath", required=True)
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

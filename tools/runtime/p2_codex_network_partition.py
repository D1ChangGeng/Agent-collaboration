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
from runtime.receiver_crypto import public_key
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from tools.runtime.p2_codex_half_loop import _command, _json, _write


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _wait(port: int, expected: bool, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _listening(port) is expected:
            return
        time.sleep(0.05)
    raise RuntimeError("reverse tunnel port did not reach expected state")


class RelayPartition:
    def __init__(self, arguments):
        self.arguments = arguments
        self.events = []
        self.old_pid = None
        self.old_birth = None
        self.restored_process = None
        self._log_stream = None

    def _snapshot(self, phase: str, pid: int | None) -> dict:
        value = {
            "phase": phase,
            "observed_at": datetime.now(UTC).isoformat(),
            "listener_pid": pid,
            "worker_port_listening": _listening(self.arguments.worker_port),
            "client_port_listening": _listening(self.arguments.client_port),
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

    def __call__(self, invocation) -> None:
        pid = int(self.arguments.relay_pid_file.read_text().strip())
        self.old_pid = pid
        self.old_birth = self._birth(pid)
        before = self._snapshot("before_partition", pid)
        before["listener_birth"] = self.old_birth
        if not before["worker_port_listening"] or not before["client_port_listening"]:
            raise RuntimeError("reverse tunnel was not healthy before partition")
        os.kill(pid, signal.SIGTERM)
        _wait(self.arguments.worker_port, False)
        _wait(self.arguments.client_port, False)
        during = self._snapshot("partitioned", None)
        if during["worker_port_listening"] or during["client_port_listening"]:
            raise RuntimeError("reverse tunnel partition did not isolate the route")
        time.sleep(self.arguments.partition_seconds)

    def restore(self, invocation) -> None:
        command = [
            sys.executable, str(self.arguments.tunnel_script), "listen",
            "--host", "127.0.0.1", "--worker-port", str(self.arguments.worker_port),
            "--client-port", str(self.arguments.client_port), "--token",
            str(self.arguments.token),
        ]
        self._log_stream = self.arguments.relay_log.open("ab")
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL,
            stdout=self._log_stream, stderr=self._log_stream,
        )
        self.restored_process = process
        self.arguments.relay_pid_file.write_text(str(process.pid))
        _wait(self.arguments.worker_port, True)
        _wait(self.arguments.client_port, True)
        # The connector pool may need one additional bounded interval to replace
        # the worker sockets destroyed with the listener.
        time.sleep(self.arguments.worker_reconnect_seconds)
        after = self._snapshot("restored", process.pid)
        after["listener_birth"] = self._birth(process.pid)
        after["logical_message_id"] = invocation.message_id
        after["operation_id"] = invocation.operation_id
        after["attempt_id"] = invocation.attempt_id
        after["dispatch_id"] = invocation.dispatch_id

    def close(self) -> dict:
        proof = {"pid": None, "birth": None, "exited": True, "returncode": None}
        if self.restored_process is not None:
            process = self.restored_process
            proof.update(pid=process.pid, birth=self._birth(process.pid), exited=False)
            process.terminate()
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5)
            proof.update(exited=True, returncode=returncode)
        if self._log_stream is not None:
            self._log_stream.close()
        return proof


def execute(arguments) -> int:
    state = _json(arguments.state)
    base = _json(arguments.profile)["postgres_dsn"]
    dsn = make_conninfo(base, options=f"-c search_path={state['schema_name']} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    signing = SigningKey(bytes.fromhex(arguments.authority_seed.read_text().strip()))
    partition = RelayPartition(arguments)
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
    fault_result = None
    recovery_result = None
    try:
        fault_result = DeliveryDispatcher(
            service, worker_id="linux-p2-network-sender",
        ).dispatch(identity)
        if fault_result.get("status") != "uncertain":
            raise RuntimeError("partitioned dispatch did not enter uncertain")
        dispatch = endpoint.store.dispatch_admission(queued.operation_id)
        if dispatch is None:
            raise RuntimeError("partitioned dispatch admission was not persisted")
        partition.restore(dispatch.admission)
        recovery_result = DeliveryDispatcher(
            service, worker_id="linux-p2-network-reconciler",
        ).reconcile_marked(identity)
    finally:
        cleanup = partition.close()
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
        "partition_events": partition.events,
        "runtime_transport": "end-to-end TLS through Runtime reverse TCP tunnel",
        "control_transport": "SSH retained only for deployment and evidence control",
        "expected_sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
        "relay_cleanup": cleanup,
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
    parser.add_argument("--partition-seconds", type=float, default=1.0)
    parser.add_argument("--worker-reconnect-seconds", type=float, default=2.0)
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

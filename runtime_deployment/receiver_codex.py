"""Production Codex receiver factory for one supervised native capacity."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.artifacts import LocalArtifactStore
from runtime.delivery_models import InvocationRequest
from runtime.domain import DomainAuthority
from runtime.models import CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_entry import DeploymentCallbacks
from runtime.recovery import AuthoritySnapshot, PostgresDelayedResponseAuthority
from runtime.response_collector import (
    NativeResponseCollector,
    artifact_response_store,
)
from runtime.systemd_supervisor import SystemdUserSupervisor

SCHEMA = "acs-receiver-codex-factory/1"
FIELDS = {
    "schema_version", "binding_id", "capacity_attempt_id", "executable",
    "executable_sha256", "codex_version", "protocol_schema", "protocol_schema_sha256",
    "cwd", "codex_home", "config_sha256", "permission_profile", "model",
    "driver_journal", "node_journal", "systemd_environment_dir", "runtime_id",
    "spawn_operation_id", "spawn_command_id", "spawn_message_id",
    "close_operation_id", "close_command_id", "close_message_id",
    "artifact_root", "collector_max_reads", "collector_interval_seconds",
}


class CodexReceiverRejected(RuntimeError):
    pass


def _text(settings: dict[str, Any], name: str) -> str:
    value = settings.get(name)
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise CodexReceiverRejected(f"Codex receiver setting {name} is invalid")
    return value


def _absolute(settings: dict[str, Any], name: str) -> str:
    value = _text(settings, name)
    if not Path(value).is_absolute() or ".." in Path(value).parts:
        raise CodexReceiverRejected(f"Codex receiver path {name} is invalid")
    return value


def validate_settings(settings: object) -> dict[str, str]:
    if not isinstance(settings, dict) or set(settings) != FIELDS:
        raise CodexReceiverRejected("Codex receiver factory settings differ")
    if settings.get("schema_version") != SCHEMA:
        raise CodexReceiverRejected("Codex receiver factory schema differs")
    for name in (
        "executable", "protocol_schema", "cwd", "codex_home", "driver_journal",
        "node_journal", "systemd_environment_dir",
        "artifact_root",
    ):
        _absolute(settings, name)
    for name in (
        "binding_id", "capacity_attempt_id", "permission_profile", "runtime_id",
        "spawn_operation_id", "spawn_command_id", "spawn_message_id",
        "close_operation_id", "close_command_id", "close_message_id",
    ):
        _text(settings, name)
    if settings.get("model") is not None:
        _text(settings, "model")
    for name in ("executable_sha256", "protocol_schema_sha256", "config_sha256"):
        value = settings.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise CodexReceiverRejected(f"Codex receiver digest {name} is invalid")
    if settings["codex_version"] not in {"0.152.1", "0.153.2"}:
        raise CodexReceiverRejected("Codex receiver version has no reviewed Driver profile")
    if Path(settings["systemd_environment_dir"]).name != "systemd-env":
        raise CodexReceiverRejected("Codex receiver Systemd environment directory differs")
    if (
        type(settings.get("collector_max_reads")) is not int
        or not 1 <= settings["collector_max_reads"] <= 120
        or type(settings.get("collector_interval_seconds")) not in {int, float}
        or not 0.1 <= settings["collector_interval_seconds"] <= 30
    ):
        raise CodexReceiverRejected("Codex receiver collector budget is invalid")
    return dict(settings)


class CodexReceiverCapacity:
    def __init__(self, config, deployment_policy_sha256: str, settings: dict[str, Any]):
        self.config = config
        self.settings = validate_settings(settings)
        self.authority = DomainAuthority(os.environ.get("ACS_RECEIVER_DSN", ""))
        if not self.authority._dsn:
            raise CodexReceiverRejected("receiver Domain DSN is unavailable")
        registration = config.binding.registration
        if (
            registration.config_sha256 != deployment_policy_sha256
            or registration.runtime_id != self.settings["runtime_id"]
        ):
            raise CodexReceiverRejected("Codex receiver deployment binding changed")
        self.binding = BindingIdentity(
            registration.node_id, registration.boot_incarnation, registration.runtime_id,
            self.settings["capacity_attempt_id"], registration.agent_slot_id,
            registration.node_binding_revision,
        )
        self.node = NodeJournal(
            self.settings["node_journal"], machine_id=registration.machine_id,
            node_id=registration.node_id, boot_incarnation=registration.boot_incarnation,
        )
        self.journal = DriverJournal(self.settings["driver_journal"])
        profile = LaunchProfile(
            self.settings["executable"], self.settings["executable_sha256"],
            self.settings["codex_version"], self.settings["protocol_schema"],
            self.settings["protocol_schema_sha256"], self.settings["cwd"],
            self.settings["codex_home"], self.settings["config_sha256"],
            self.settings["permission_profile"],
            {
                # The reviewed Codex distribution may resolve its optional
                # code-mode helper by name even when the packet exposes no
                # tools.  Keep resolution inside the same digest-pinned,
                # owner-controlled capacity as the executable.
                "PATH": (
                    str(Path(self.settings["executable"]).parent)
                    + ":/opt/acs/codex-sandbox/bin:/usr/bin:/bin"
                ),
                "HOME": str(Path(self.settings["codex_home"]).parent / "home"),
                "TMPDIR": str(Path(self.settings["codex_home"]).parent / "tmp"),
                "LANG": "C.UTF-8",
            },
            self.settings.get("model"),
        )
        self.supervisor = SystemdUserSupervisor(
            tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
            termination_timeout=10,
            environment_directory=Path(self.settings["systemd_environment_dir"]),
        )
        self.driver = CodexAppServerDriver(
            self.settings["binding_id"], profile, self.journal,
            identity=self.binding, check_current=self._current, supervisor=self.supervisor,
            rpc_timeout=30,
        )
        self.adapter = NativeDeliveryAdapter(
            self.driver, authorize_invocation=self._authorize_invocation,
        )
        self.bridge = ReceiverNativeDeliveryBridge(
            config.ledger_path, self.adapter,
            read_domain_marker=self.authority.receiver_transport.dispatch_marker_current,
        )
        self.artifact_store = LocalArtifactStore(
            self.settings["artifact_root"], scope_id=registration.scope_id,
        )
        self.projector = PostgresDelayedResponseAuthority(
            self.authority._dsn, self._projection_snapshot,
        )
        self.collector = NativeResponseCollector(
            self.adapter, self.node.response_outbox(),
            artifact_response_store(self.artifact_store), self.projector.project,
        )
        self._collector_threads: dict[str, threading.Thread] = {}
        self._collector_errors: dict[str, str] = {}
        self._collector_lock = threading.Lock()
        self._closed = False
        try:
            self.driver.spawn(self._lifecycle_operation("spawn"))
        except BaseException:
            # A failed native spawn may already own a supervised process tree
            # and a kernel Driver claim.  Constructor failure must not orphan
            # either resource because no DeploymentCallbacks.close hook exists
            # yet for the entrypoint to invoke.
            try:
                if self.driver.owned is not None:
                    self.supervisor.terminate_tree(self.driver.owned)
                self.driver.detach_transport()
            finally:
                self.supervisor.close()
            raise

    def _lifecycle_operation(self, action: str) -> AuthorizedOperation:
        prefix = "spawn" if action == "spawn" else "close"
        return AuthorizedOperation(
            self.settings[prefix + "_operation_id"],
            self.settings[prefix + "_command_id"],
            self.settings[prefix + "_message_id"],
            self.authority.context.grant_ref,
            min(self.config.binding.registration.expires_at,
                datetime.now(UTC) + timedelta(minutes=5)),
        )

    def _domain_invocation(self, operation: AuthorizedOperation) -> InvocationRequest:
        if not operation.operation_id.startswith("delivery-invocation:"):
            raise CodexReceiverRejected("Codex Driver operation is outside a Delivery Attempt")
        attempt_id = operation.operation_id.removeprefix("delivery-invocation:")
        with self.authority._connect() as connection:
            row = connection.execute(
                "SELECT a.invocation_json,m.command_json,m.deadline FROM delivery_attempts a "
                "JOIN delivery_messages m ON m.tenant_id=a.tenant_id AND m.message_id=a.message_id "
                "WHERE a.tenant_id=%s AND a.attempt_id=%s",
                (self.authority.tenant_id, attempt_id),
            ).fetchone()
            if row is None or not isinstance(row[0], dict):
                raise CodexReceiverRejected("Codex Driver Attempt is unavailable")
            invocation = InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)
            command = CommandEnvelope.model_validate_json(json.dumps(row[1], default=str), strict=True)
            self.authority._authorize(
                command, connection.cursor(), "runtime.invoke",
                invocation.envelope.packet.target_scope_id,
            )
        if (
            (invocation.invocation_id, invocation.command_id, invocation.message_id)
            != (operation.operation_id, operation.command_id, operation.message_id)
            or operation.deadline > row[2]
        ):
            raise CodexReceiverRejected("Codex Driver operation lineage changed")
        return invocation

    def _current(self, operation: AuthorizedOperation, observed: BindingIdentity) -> None:
        if observed != self.binding or operation.grant_ref != self.authority.context.grant_ref:
            raise CodexReceiverRejected("Codex receiver Driver binding changed")
        if operation.operation_id in {
            self.settings["spawn_operation_id"], self.settings["close_operation_id"],
        }:
            return
        self._domain_invocation(operation)

    def _authorize_invocation(self, invocation, observed) -> AuthorizedOperation:
        if observed != self.binding:
            raise CodexReceiverRejected("Codex receiver invocation binding changed")
        operation = AuthorizedOperation(
            invocation.invocation_id, invocation.command_id, invocation.message_id,
            invocation.envelope.grant_ref, invocation.envelope.packet.deadline,
        )
        self._domain_invocation(operation)
        return operation

    def _projection_snapshot(self, cursor, observation) -> AuthoritySnapshot:
        native = observation.identity
        message = cursor.execute(
            "SELECT packet_json,envelope_json,deadline,policy_hash,accepted_state_digest "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        attempt = cursor.execute(
            "SELECT invocation_json,attempt_id,status FROM delivery_attempts "
            "WHERE tenant_id=%s AND message_id=%s ORDER BY ordinal DESC LIMIT 1 FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        if message is None or attempt is None or not isinstance(attempt[0], dict):
            raise CodexReceiverRejected("current receiver projection identity is absent")
        recorded = InvocationRequest.model_validate_json(json.dumps(attempt[0]), strict=True)
        committed = NativeResponseCollector.dispatch_identity(recorded)
        envelope = message[1]
        grant = cursor.execute(
            "SELECT revoked_at,expires_at,principal_ref,authority_id,authority_incarnation "
            "FROM grants WHERE grant_ref=%s AND tenant_id=%s FOR UPDATE",
            (envelope["grant_ref"], native.tenant_id),
        ).fetchone()
        work = cursor.execute(
            "SELECT state,execution_status FROM work_items WHERE work_item_id=%s "
            "AND tenant_id=%s FOR UPDATE",
            (message[0]["work_item_id"], native.tenant_id),
        ).fetchone()
        authorized = bool(
            grant and grant[0] is None and grant[1] > datetime.now(UTC)
            and grant[2] == envelope["principal_ref"]
            and (grant[3], grant[4]) == (
                self.authority.context.authority_id,
                self.authority.context.authority_incarnation,
            )
        )
        producer = False
        try:
            self.adapter._check_binding()
            producer = (
                self.node.node_id == native.node_id
                and self.node.boot_incarnation == native.boot_incarnation
                and self.authority.receiver_transport.dispatch_marker_current(recorded)
                and self.driver.journal.read(native.invocation_id)["state"] == "acknowledged"
            )
        except (RuntimeError, ValueError, TypeError, KeyError):
            producer = False
        return AuthoritySnapshot(
            committed_identity=committed, producer_authenticated=producer,
            current_authority_valid=authorized,
            task_valid=bool(work and work[0] == "candidate"
                            and work[1] not in {"blocked", "failed", "cancelled"}),
            current_attempt_id=attempt[1],
            current_accepted_revision=message[0]["accepted_revision"],
            current_accepted_state_digest=message[4], deadline=message[2],
            principal_ref=envelope["principal_ref"], grant_ref=envelope["grant_ref"],
            policy_version="receiver-codex:" + message[3],
        )

    def _collect(self, invocation: InvocationRequest) -> None:
        try:
            for _ in range(self.settings["collector_max_reads"]):
                try:
                    self.collector.collect_and_project(invocation)
                    return
                except Exception as error:  # bounded readback; never reinvokes
                    last = type(error).__name__
                    time.sleep(self.settings["collector_interval_seconds"])
            with self._collector_lock:
                self._collector_errors[invocation.invocation_id] = last
        except BaseException as error:
            with self._collector_lock:
                self._collector_errors[invocation.invocation_id] = type(error).__name__

    def _start_collector(self, invocation: InvocationRequest) -> None:
        with self._collector_lock:
            existing = self._collector_threads.get(invocation.invocation_id)
            if existing is not None:
                return
            thread = threading.Thread(
                target=self._collect, args=(invocation,),
                name="acs-receiver-codex-collector", daemon=True,
            )
            self._collector_threads[invocation.invocation_id] = thread
            thread.start()

    def authorize_current(self, admission) -> bool:
        return self.authority.receiver_transport.current_authority(admission)

    def native_invoke(self, admission):
        invocation = self.bridge._invocation(admission)
        result = self.bridge(admission)
        self._start_collector(invocation)
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            for thread in tuple(self._collector_threads.values()):
                thread.join(timeout=30)
            if any(thread.is_alive() for thread in self._collector_threads.values()):
                raise CodexReceiverRejected("Codex receiver collector remains live")
            if self.driver.owned is not None and self.driver.owned.process.poll() is None:
                self.driver.terminate(self._lifecycle_operation("close"))
            self.driver.detach_transport()
        finally:
            self.supervisor.close()
        self.artifact_store.close()

def callbacks(config, deployment_policy_sha256, settings):
    capacity = CodexReceiverCapacity(config, deployment_policy_sha256, settings)
    registration = config.binding.registration
    return DeploymentCallbacks(
        deployment_policy_sha256=deployment_policy_sha256,
        endpoint_id=registration.endpoint_id, runtime_id=registration.runtime_id,
        authorize_current=capacity.authorize_current,
        native_invoke=capacity.native_invoke,
        close=capacity.close,
    )

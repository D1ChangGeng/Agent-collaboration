"""Production Codex receiver factory for one supervised native capacity."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from runtime.codex_driver import (
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.connection_clock import ConnectionClock
from runtime.domain import DomainAuthority
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.posix_process_supervisor import PosixProcessSupervisor
from runtime.receiver_config import receiver_clock_identity
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_entry import DeploymentCallbacks
from runtime.supervisor import WindowsJobSupervisor
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_deployment.receiver_authority import (
    NativeReceiverAuthority,
    NativeReceiverRejected,
    bind_registered_receiver,
)

SCHEMA = "acs-receiver-codex-factory/1"
FIELDS = {
    "schema_version", "binding_id", "capacity_attempt_id", "executable",
    "executable_sha256", "codex_version", "protocol_schema", "protocol_schema_sha256",
    "model_catalog", "model_catalog_sha256", "cwd", "codex_home", "config_sha256",
    "permission_profile", "model", "source_commit", "source_tree",
    "driver_journal", "node_journal", "systemd_environment_dir", "runtime_id",
    "spawn_operation_id", "spawn_command_id", "spawn_message_id",
    "close_operation_id", "close_command_id", "close_message_id",
    "artifact_root", "collector_max_reads", "collector_interval_seconds",
}
RETIRED_FIELDS = {"artifact_root", "collector_max_reads", "collector_interval_seconds"}


CodexReceiverRejected = NativeReceiverRejected


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


def native_settings(settings):
    """Resolve the selected environment at preparation time; digests are observations."""
    required = {"schema_version", "binding_id", "capacity_attempt_id", "executable", "cwd", "codex_home",
                "driver_journal", "node_journal", "runtime_id"}
    if not isinstance(settings, dict) or not required <= set(settings) or set(settings)-FIELDS:
        raise CodexReceiverRejected("native receiver environment is incomplete")
    current = dict(settings)
    private = Path(current["driver_journal"]).parent
    current.setdefault("protocol_schema", str(private/"api-schema.json"))
    current.setdefault("model_catalog", str(private/"model-catalog.json"))
    current.setdefault("systemd_environment_dir", str(private/"process-manager"))
    current.setdefault("permission_profile", "native-user-settings")
    current.setdefault("model", None)
    current.setdefault("source_commit", "unknown")
    current.setdefault("source_tree", "unknown")
    for prefix in ("spawn", "close"):
        for kind in ("operation", "command", "message"):
            current.setdefault(prefix+"_"+kind+"_id", f"native-{prefix}-{kind}:{current['runtime_id']}")
    for path, digest in (("executable", "executable_sha256"), ("protocol_schema", "protocol_schema_sha256"),
                         ("model_catalog", "model_catalog_sha256")):
        value = Path(current[path])
        current[digest] = hashlib.sha256(value.read_bytes()).hexdigest() if value.is_file() else "not-measured"
    config = Path(current["codex_home"])/"config.toml"
    current["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else "not-configured"
    observed = subprocess.run([current["executable"], "--version"], capture_output=True, text=True, timeout=10, check=True)
    current["codex_version"] = observed.stdout.strip().removeprefix("codex-cli ")
    return current

def validate_settings(settings: object, *, execution_mode="restricted") -> dict[str, str]:
    if execution_mode == "native":
        settings = native_settings(settings)
    if not isinstance(settings, dict) or not FIELDS-RETIRED_FIELDS <= set(settings) or set(settings)-FIELDS:
        raise CodexReceiverRejected("Codex receiver factory settings differ")
    if settings.get("schema_version") != SCHEMA:
        raise CodexReceiverRejected("Codex receiver factory schema differs")
    for name in (
        "executable", "protocol_schema", "cwd", "codex_home", "driver_journal",
        "node_journal", "systemd_environment_dir",
    ):
        _absolute(settings, name)
    if "artifact_root" in settings:
        _absolute(settings, "artifact_root")
    for name in (
        "binding_id", "capacity_attempt_id", "permission_profile", "runtime_id",
        "source_commit", "source_tree",
        "spawn_operation_id", "spawn_command_id", "spawn_message_id",
        "close_operation_id", "close_command_id", "close_message_id",
    ):
        _text(settings, name)
    for name in ("source_commit", "source_tree"):
        if execution_mode == "restricted" and not re.fullmatch(r"[a-f0-9]{40}", settings[name]):
            raise CodexReceiverRejected(f"Codex receiver {name} is invalid")
    if settings.get("model") is not None:
        _text(settings, "model")
    for name in ("executable_sha256", "protocol_schema_sha256", "config_sha256"):
        value = settings.get(name)
        if execution_mode == "restricted" and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise CodexReceiverRejected(f"Codex receiver digest {name} is invalid")
    if execution_mode == "restricted" and settings["codex_version"] not in {
        "0.152.1", "0.153.2", "0.153.4", "0.155.0", "0.155.0-alpha.2.6",
    }:
        raise CodexReceiverRejected("Codex receiver version has no reviewed Driver profile")
    if execution_mode == "restricted" and (
        settings["codex_version"] == "0.155.0" and settings["permission_profile"] != "achp-engineer"
        or settings["codex_version"] == "0.155.0-alpha.2.6"
        and settings["permission_profile"] != ":workspace"
    ):
        raise CodexReceiverRejected("Codex receiver permission profile is not reviewed for version")
    _absolute(settings, "model_catalog")
    value = settings["model_catalog_sha256"]
    if execution_mode == "restricted" and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
        raise CodexReceiverRejected("Codex receiver model catalog digest is invalid")
    catalog = Path(settings["model_catalog"])
    if execution_mode == "restricted" and (not catalog.is_file() or catalog.is_symlink()):
        raise CodexReceiverRejected("Codex receiver model catalog is unavailable")
    if execution_mode == "restricted" and hashlib.sha256(catalog.read_bytes()).hexdigest() != value:
        raise CodexReceiverRejected("Codex receiver model catalog differs from pinned profile")
    if execution_mode == "restricted" and os.name == "posix" and Path(settings["systemd_environment_dir"]).name != "systemd-env":
        raise CodexReceiverRejected("Codex receiver Systemd environment directory differs")
    if execution_mode == "restricted" and os.name == "nt" and Path(settings["systemd_environment_dir"]).name != "windows-job":
        raise CodexReceiverRejected("Codex receiver Windows Job directory differs")
    if (
        type(settings.get("collector_max_reads", 120)) is not int
        or not 1 <= settings.get("collector_max_reads", 120) <= 120
        or type(settings.get("collector_interval_seconds", 1.0)) not in {int, float}
        or not 0.1 <= settings.get("collector_interval_seconds", 1.0) <= 30
    ):
        raise CodexReceiverRejected("Codex receiver collector budget is invalid")
    return dict(settings)


class CodexReceiverCapacity(NativeReceiverAuthority):
    def __init__(self, config, deployment_policy_sha256: str, settings: dict[str, Any]):
        self.config = config
        self.settings = validate_settings(settings, execution_mode="native" if getattr(config, "access_mode", "shared") == "owner" else "restricted")
        if getattr(config, "access_mode", "shared") == "owner":
            instance = uuid.uuid4().hex
            for prefix in ("spawn", "close"):
                for kind in ("operation", "command", "message"):
                    self.settings[prefix+"_"+kind+"_id"] += ":" + instance
        self.authority = (DomainAuthority(os.environ.get("ACS_RECEIVER_DSN", ""), access_mode="owner")
                          if getattr(config, "access_mode", "shared") == "owner" else
                          DomainAuthority(os.environ.get("ACS_RECEIVER_DSN", "")))
        if not self.authority._dsn:
            raise CodexReceiverRejected("receiver Domain DSN is unavailable")
        registration = config.binding.registration
        self.binding = bind_registered_receiver(self.authority, registration, deployment_policy_sha256,
                                                self.settings["runtime_id"], self.settings["capacity_attempt_id"])
        self.node = NodeJournal(
            self.settings["node_journal"], machine_id=registration.machine_id,
            node_id=registration.node_id, boot_incarnation=registration.boot_incarnation,
        )
        self.journal = DriverJournal(self.settings["driver_journal"])
        if os.name == "nt":
            native_path = str(Path(self.settings["executable"]).parent)
            environment = {
                "PATH": native_path + os.pathsep + os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
                "HOME": str(Path(self.settings["codex_home"]).parent / "home"),
                "TMP": str(Path(self.settings["codex_home"]).parent / "tmp"),
                "TEMP": str(Path(self.settings["codex_home"]).parent / "tmp"),
                "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "APPDATA": os.environ.get("APPDATA", ""),
                "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            }
        else:
            environment = {
                "PATH": (
                    str(Path(self.settings["executable"]).parent)
                    + ":/opt/acs/codex-sandbox/bin:/usr/bin:/bin"
                ),
                "HOME": str(Path(self.settings["codex_home"]).parent / "home"),
                "TMPDIR": str(Path(self.settings["codex_home"]).parent / "tmp"),
                "LANG": "C.UTF-8",
            }
        if getattr(config, "access_mode", "shared") == "owner":
            environment = dict(os.environ)
            environment["PATH"] = str(Path(self.settings["executable"]).parent) + os.pathsep + environment.get("PATH", "")
            environment["CODEX_HOME"] = self.settings["codex_home"]
        profile = LaunchProfile(
            self.settings["executable"], self.settings["executable_sha256"],
            self.settings["codex_version"], self.settings["protocol_schema"],
            self.settings["protocol_schema_sha256"], self.settings["cwd"],
            self.settings["codex_home"], self.settings["config_sha256"],
            self.settings["permission_profile"],
            environment,
            self.settings.get("model"),
            **({"execution_mode": "native"} if getattr(config, "access_mode", "shared") == "owner" else {}),
        )
        self.supervisor = (
            WindowsJobSupervisor(max_processes=None if getattr(config, "access_mode", "shared") == "owner" else 64, termination_timeout=10)
            if os.name == "nt"
            else PosixProcessSupervisor(termination_timeout=10) if getattr(config, "access_mode", "shared") == "owner"
            else SystemdUserSupervisor(
                tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
                termination_timeout=10,
                environment_directory=Path(self.settings["systemd_environment_dir"]),
            )
        )
        self.clock = ConnectionClock.from_authority(
            self.authority, identity=receiver_clock_identity(config),
        )
        self.journal.clock = self.clock
        self.driver = CodexAppServerDriver(
            self.settings["binding_id"], profile, self.journal,
            identity=self.binding, check_current=self._current, supervisor=self.supervisor,
            rpc_timeout=120 if os.name == "nt" else 30, clock=self.clock,
        )
        self.adapter = NativeDeliveryAdapter(
            self.driver, authorize_invocation=self._authorize_invocation,
            clock=self.clock,
            configure_runtime=self._prepare_runtime, inspect_runtime=self.health,
        )
        self.bridge = ReceiverNativeDeliveryBridge(
            config.ledger_path, self.adapter,
            read_domain_marker=self.authority.receiver_transport.dispatch_marker_current,
        )
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

    def health(self):
        operation = self._lifecycle_operation("spawn")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority.enrollment._active_runtime(cursor, self.config.binding.registration.runtime_id)
        with self.driver._lock:
            view = self.driver._inspect(operation)
        state = view.get("thread", {}).get("status", {}).get("type")
        return {"state": "idle" if state == "idle" else "busy" if state in {"active", "running"} else "unknown",
                "harness": "codex", "version": self.driver.profile.version,
                "session_ref": self.driver.thread_id, "observation": "native_driver_readback"}

    def _prepare_runtime(self):
        if self.driver.thread_id is None:
            self.driver.spawn(self._lifecycle_operation("spawn"))
        return self.health()













def callbacks(config, deployment_policy_sha256, settings):
    capacity = CodexReceiverCapacity(config, deployment_policy_sha256, settings)
    registration = config.binding.registration
    return DeploymentCallbacks(
        deployment_policy_sha256=deployment_policy_sha256,
        endpoint_id=registration.endpoint_id, runtime_id=registration.runtime_id,
        authorize_current=capacity.authorize_current,
        native_invoke=capacity.native_invoke,
        readiness=capacity.readiness,
        close=capacity.close,
        clock=capacity.clock,
    )

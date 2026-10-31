"""Owner-selected OpenCode receiver using the real HTTP Driver and Node authority."""
from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from runtime.codex_driver import DriverJournal, file_digest
from runtime.connection_clock import ConnectionClock
from runtime.domain import DomainAuthority
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.posix_process_supervisor import PosixProcessSupervisor
from runtime.receiver_config import receiver_clock_identity
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_entry import DeploymentCallbacks
from runtime.supervisor import WindowsJobSupervisor
from runtime_deployment.receiver_authority import (
    NativeReceiverAuthority,
    NativeReceiverRejected,
    bind_registered_receiver,
)

SCHEMA = "acs-receiver-opencode-factory/1"
REQUIRED = {"schema_version", "binding_id", "capacity_attempt_id", "executable", "cwd",
            "driver_journal", "node_journal", "runtime_id"}
OPTIONAL = {"home", "config_root", "data_root", "state_root", "cache_root", "temp_root",
            "agent", "provider_id", "model_id", "schema_path"}


def validate_settings(settings):
    if not isinstance(settings, dict) or not REQUIRED <= set(settings) or set(settings) - REQUIRED - OPTIONAL:
        raise NativeReceiverRejected("OpenCode receiver settings differ")
    if settings.get("schema_version") != SCHEMA:
        raise NativeReceiverRejected("OpenCode receiver schema differs")
    current = dict(settings)
    for name in REQUIRED - {"schema_version"}:
        value = current[name]
        if not isinstance(value, str) or not value or "\0" in value or len(value) > 4096:
            raise NativeReceiverRejected("invalid OpenCode receiver setting: " + name)
    home = Path(current.setdefault("home", str(Path.home())))
    inherit = home == Path.home()
    defaults = {"config_root": ("XDG_CONFIG_HOME", home/".config"),
                "data_root": ("XDG_DATA_HOME", home/".local/share"),
                "state_root": ("XDG_STATE_HOME", home/".local/state"),
                "cache_root": ("XDG_CACHE_HOME", home/".cache"),
                "temp_root": ("TMPDIR", Path(tempfile.gettempdir()))}
    for name, (env_key, fallback) in defaults.items():
        current.setdefault(name, os.environ.get(env_key, str(fallback)) if inherit else str(fallback))
    current.setdefault("schema_path", str(Path(current["driver_journal"]).parent/"openapi.json"))
    for name in ("executable", "cwd", "driver_journal", "node_journal", "home", "config_root", "data_root",
                 "state_root", "cache_root", "temp_root", "schema_path"):
        value = current[name]
        if not isinstance(value, str) or "\0" in value or not Path(value).is_absolute() or ".." in Path(value).parts:
            raise NativeReceiverRejected("OpenCode receiver path must be absolute: " + name)
    for name in ("agent", "provider_id", "model_id"):
        value = current.setdefault(name, None)
        if value is not None and (not isinstance(value, str) or not value or "\0" in value or len(value) > 256):
            raise NativeReceiverRejected("invalid native selection: " + name)
    if (current["provider_id"] is None) != (current["model_id"] is None):
        raise NativeReceiverRejected("OpenCode provider and model must be selected together")
    return current


class OpenCodeReceiverCapacity(NativeReceiverAuthority):
    def __init__(self, config, deployment_policy_sha256, settings):
        if getattr(config, "access_mode", "shared") != "owner":
            raise NativeReceiverRejected("OpenCode receiver requires a separately qualified Shared profile")
        self.config = config
        self.settings = validate_settings(settings)
        instance = uuid.uuid4().hex
        for prefix in ("spawn", "close"):
            for kind in ("operation", "command", "message"):
                self.settings[prefix+"_"+kind+"_id"] = f"native-{prefix}-{kind}:{self.settings['runtime_id']}:{instance}"
        dsn = os.environ.get("ACS_RECEIVER_DSN")
        if not dsn:
            raise NativeReceiverRejected("receiver Domain DSN is unavailable")
        self.authority = DomainAuthority(dsn, access_mode="owner")
        registration = config.binding.registration
        self.binding = bind_registered_receiver(self.authority, registration, deployment_policy_sha256,
                                               self.settings["runtime_id"], self.settings["capacity_attempt_id"])
        self.node = NodeJournal(self.settings["node_journal"], machine_id=registration.machine_id,
            node_id=registration.node_id, boot_incarnation=registration.boot_incarnation)
        self.clock = ConnectionClock.from_authority(self.authority, identity=receiver_clock_identity(config))
        self.journal = DriverJournal(self.settings["driver_journal"], clock=self.clock)
        for name in ("home", "config_root", "data_root", "state_root", "cache_root", "temp_root"):
            Path(self.settings[name]).mkdir(mode=0o700, parents=True, exist_ok=True)
        binary = self.settings["executable"]
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        environment = dict(os.environ)
        environment["PATH"] = str(Path(binary).parent) + os.pathsep + environment.get("PATH", "")
        settings = self.settings
        config_file = Path(settings["config_root"])/"opencode/opencode.json"
        profile = OpenCodeLaunchProfile(binary, file_digest(binary), version, settings["schema_path"], "not-measured",
            settings["cwd"], settings["home"], settings["config_root"], settings["data_root"], settings["state_root"],
            settings["cache_root"], settings["temp_root"], file_digest(config_file) if config_file.is_file() else "not-configured",
            settings["agent"], settings["provider_id"], settings["model_id"], environment, execution_mode="native")
        self.supervisor = WindowsJobSupervisor(max_processes=None, termination_timeout=10) if os.name == "nt" else PosixProcessSupervisor(termination_timeout=10)
        self.driver = OpenCodeNativeDriver(settings["binding_id"], profile, self.journal, identity=self.binding,
            check_current=self._current, supervisor=self.supervisor, clock=self.clock)
        self._closed = False
        try:
            self.adapter = NativeDeliveryAdapter(self.driver, authorize_invocation=self._authorize_invocation,
                clock=self.clock, configure_runtime=self._prepare_runtime, inspect_runtime=self.health)
            self.bridge = ReceiverNativeDeliveryBridge(config.ledger_path, self.adapter,
                read_domain_marker=self.authority.receiver_transport.dispatch_marker_current)
            self.driver.spawn(self._lifecycle_operation("spawn"))
        except BaseException:
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
            self.authority.enrollment._active_runtime(cursor, self.binding.runtime_id)
        view = self.driver.inspect(operation)
        status = view.get("status", {}).get("type")
        return {"state": "idle" if status == "idle" else "busy" if status in {"busy", "retry"} else "unknown",
            "harness": "opencode", "version": self.driver.profile.version, "session_ref": self.driver.session_id,
            "observation": "native_driver_readback"}

    def _prepare_runtime(self):
        if self.driver.session_id is None:
            self.driver.spawn(self._lifecycle_operation("spawn"))
        return self.health()


def callbacks(config, deployment_policy_sha256, settings):
    capacity = OpenCodeReceiverCapacity(config, deployment_policy_sha256, settings)
    registration = config.binding.registration
    return DeploymentCallbacks(deployment_policy_sha256=deployment_policy_sha256,
        endpoint_id=registration.endpoint_id, runtime_id=registration.runtime_id,
        authorize_current=capacity.authorize_current, native_invoke=capacity.native_invoke,
        readiness=capacity.readiness, close=capacity.close, clock=capacity.clock)

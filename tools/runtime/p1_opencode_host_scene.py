"""One budgeted OpenCode HostNode dispatch with durable six-layer readback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.codex_driver import AuthorizedOperation
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.p1_codex_host_node import CodexHostRequest
from runtime.p1_opencode_host_node import OpenCodeHostNodeEndpoint, OpenCodeHostResult
from runtime.receiver_paths import (
    PathSecurityRejected,
    optional_private_file_identity,
    private_parent,
)
from tools.runtime.p1_codex_host_scene import _systemctl, _unit_state
from tools.runtime.p1_opencode_gate import OpenCodeGateAdmission
from tools.runtime.p1_opencode_projection import project_original_opencode_terminal
from tools.runtime.p1_opencode_readback import read_original_opencode_scene
from tools.runtime.p1_opencode_temporal import OpenCodeTemporalDispatcher


class OpenCodeHostUncertain(RuntimeError):
    pass


def postflight_opencode_run(root: Path, run_id: str) -> dict[str, Any]:
    if (
        os.name != "posix"
        or not re.fullmatch(r"p1-run-[a-f0-9]{32}", run_id)
        or root != Path(f"/run/user/{os.geteuid()}/acs-p1-opencode") / run_id
    ):
        raise OpenCodeHostUncertain("OpenCode postflight root is outside one run")
    try:
        descriptor, _ = private_parent(root)
        os.close(descriptor)
    except (OSError, PathSecurityRejected) as error:
        raise OpenCodeHostUncertain("OpenCode postflight root is unsafe") from error
    ledger = root / "ledger" / "host.sqlite"
    try:
        identity = optional_private_file_identity(ledger)
    except (OSError, PathSecurityRejected) as error:
        raise OpenCodeHostUncertain("OpenCode postflight ledger path is unsafe") from error
    boot_state = None
    boot_proof = None
    if identity is not None:
        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT state,proof_json FROM codex_host_boot WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is not None:
            boot_state, encoded = row
            boot_proof = json.loads(encoded) if encoded else None
    response = _systemctl(
        "list-units", "--all", "--plain", "--no-legend", f"acs-{run_id}-*.service"
    )
    if response.returncode:
        raise OpenCodeHostUncertain("OpenCode postflight user manager is unavailable")
    units = sorted({line.split()[0] for line in response.stdout.splitlines() if line.strip()})
    quarantined = []
    for unit in units:
        active, _load, members = _unit_state(unit, run_id)
        if active == "active" or members:
            stopped = _systemctl("stop", unit)
            if stopped.returncode:
                raise OpenCodeHostUncertain("OpenCode postflight could not stop original unit")
            quarantined.append(unit)
        until = time.monotonic() + 10
        while True:
            active, _load, members = _unit_state(unit, run_id)
            if active in {"inactive", "failed"} and members == []:
                break
            if time.monotonic() >= until:
                raise OpenCodeHostUncertain("OpenCode original cgroup remains live")
            time.sleep(0.05)
    environment_dir = root / "systemd-env"
    if environment_dir.is_symlink():
        raise OpenCodeHostUncertain("OpenCode EnvironmentFile directory changed")
    environment_files = 0
    if environment_dir.exists():
        try:
            descriptor, _ = private_parent(environment_dir)
            try:
                environment_files = len(os.listdir(descriptor))
            finally:
                os.close(descriptor)
        except (OSError, PathSecurityRejected) as error:
            raise OpenCodeHostUncertain("OpenCode EnvironmentFile path is unsafe") from error
    clean_boot = boot_state == "stopped" and (
        isinstance(boot_proof, dict)
        and boot_proof.get("verified") is True
        and boot_proof.get("remaining_pids") == []
    )
    return {
        "schema_version": "acs-p1-opencode-postflight/1",
        "run_id": run_id,
        "status": "clean" if environment_files == 0 and (
            (boot_state is None and not units) or (clean_boot and not quarantined)
        ) else "uncertain",
        "boot_state": boot_state,
        "units_seen": units,
        "quarantined_units": quarantined,
        "remaining_pids": [],
        "environment_files_remaining": environment_files,
        "observed_at": datetime.now(UTC).isoformat(),
    }


class OpenCodeHostSceneService:
    """A trusted host performs one original operation; socket peers only address it."""

    def __init__(
        self,
        host: OpenCodeHostNodeEndpoint,
        node: NodeJournal,
        driver: OpenCodeNativeDriver,
        adapter: Any,
        temporal: OpenCodeTemporalDispatcher,
        admission: OpenCodeGateAdmission,
        *,
        scene_path: Path,
        budget_path: Path,
        artifact_root: Path,
        environment_dir: Path,
        temporal_namespace: str,
    ) -> None:
        if (
            host.dispatcher is not temporal
            or temporal.service is not host.dispatcher.service
            or admission.run_id != host.policy.run_id
            or admission.machine_id != node.machine_id
            or admission.node_id != node.node_id
            or driver.identity.node_id != node.node_id
            or driver.identity.node_boot_id != node.boot_incarnation
        ):
            raise OpenCodeHostUncertain("OpenCode HostNode scene components differ")
        self.host, self.node, self.driver, self.adapter = host, node, driver, adapter
        self.temporal, self.admission = temporal, admission
        self.scene_path, self.budget_path = scene_path, budget_path
        self.artifact_root, self.environment_dir = artifact_root, environment_dir
        self.temporal_namespace = temporal_namespace
        self._attempted = False
        self._dispatch: dict[str, Any] | None = None
        self._projection: dict[str, Any] | None = None
        self._os_proof: dict[str, Any] | None = None
        self._readback: dict[str, Any] | None = None
        self._key_identity: tuple[int, int, int, int, int] | None = None

    def _current_admission(self) -> OpenCodeGateAdmission:
        observed = OpenCodeGateAdmission.load(
            self.scene_path, self.admission.scene_sha256,
            self.budget_path, self.admission.budget_sha256,
            source_commit=self.admission.source_commit,
            source_tree=self.admission.source_tree,
        ).bind_run(
            self.admission.run_id, self.admission.machine_id, self.admission.node_id
        )
        observed.assert_native_profile(self.driver.profile)
        return observed

    def _fresh_result(self, request: CodexHostRequest) -> OpenCodeHostResult:
        base = OpenCodeHostResult.from_internal(
            self.host.handle(request.model_copy(update={"action": "readback"}))
        )
        if self._dispatch is None or self._projection is None or self._os_proof is None:
            return base
        readback = read_original_opencode_scene(
            authority=self._dispatch["authority"],
            node=self.node,
            driver=self.driver,
            projection=self._projection,
            artifact_root=self.artifact_root,
            message_id=request.message_id,
            operation_id=request.operation_id,
            attempt_id=self._dispatch["attempt_id"],
            dispatch_id=self._dispatch["dispatch_id"],
            workflow_id=self.temporal.last["workflow_id"],
            temporal_run_id=self.temporal.last["provider_run_id"],
            temporal_endpoint=self.temporal.endpoint,
            temporal_namespace=self.temporal_namespace,
            os_proof=self._os_proof,
            expected_text="ACS_P1_OPENCODE_API_OK",
            run_id=self.admission.run_id,
            source_commit=self.admission.source_commit,
            source_tree=self.admission.source_tree,
        )
        self.admission.assert_final_lineage(readback)
        if self._readback is not None and readback != self._readback:
            raise OpenCodeHostUncertain("OpenCode final authority readback changed")
        self._readback = readback
        digest = hashlib.sha256(
            json.dumps(readback, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return base.model_copy(update={
            "scene_readback": readback, "scene_readback_sha256": digest,
        })

    def handle(self, request: CodexHostRequest) -> OpenCodeHostResult:
        if request.action == "readback" or self._readback is not None:
            return self._fresh_result(request)
        if self._attempted:
            raise OpenCodeHostUncertain("OpenCode original prompt is unresolved")
        admission = self._current_admission()
        self._key_identity = admission.key_reference_identity()
        self._attempted = True
        policy = self.host.policy
        spawn = AuthorizedOperation(
            policy.run_id + "-spawn", policy.run_id + "-command-spawn",
            policy.run_id + "-message-spawn",
            self.host.dispatcher.service.authority.context.grant_ref,
            policy.deadline,
        )
        self.host.start_native(request, spawn)
        try:
            if admission.key_reference_identity() != self._key_identity:
                raise OpenCodeHostUncertain("OpenCode key reference changed before dispatch")
            dispatched = self.host.handle(request)
            if dispatched.status != "delivered" or not dispatched.attempt_id:
                raise OpenCodeHostUncertain("OpenCode original Temporal dispatch lacks native ACK")
            if self.temporal.last is None:
                raise OpenCodeHostUncertain("OpenCode original Temporal Workflow/Run is unavailable")
            attempt_id = dispatched.attempt_id
            self._dispatch = {
                "authority": self.host.dispatcher.service.authority,
                "identity": {
                    "tenant_id": request.tenant_id,
                    "message_id": request.message_id,
                    "operation_id": request.operation_id,
                },
                "attempt_id": attempt_id,
                "invocation_id": "delivery-invocation:" + attempt_id,
                "dispatch_id": dispatched.dispatch_id,
            }
            self._projection = project_original_opencode_terminal(
                self._dispatch, self.node, self.driver, self.adapter,
                self.artifact_root, max_collect_reads=admission.scene["max_collect_reads"],
            )
        finally:
            if self.driver.owned is not None:
                try:
                    stopped = self.host.stop_native()
                    self.driver.detach_transport()
                except Exception as error:
                    raise OpenCodeHostUncertain("OpenCode host termination is unverified") from error
                self._os_proof = stopped
                if admission.key_reference_identity() != self._key_identity:
                    raise OpenCodeHostUncertain("OpenCode key reference changed after stop")
                if not self.environment_dir.is_dir() or any(self.environment_dir.iterdir()):
                    raise OpenCodeHostUncertain("OpenCode EnvironmentFile residue remains")
        if self._dispatch is None or self._projection is None:
            raise OpenCodeHostUncertain("OpenCode original attempt has no terminal projection")
        return self._fresh_result(request)

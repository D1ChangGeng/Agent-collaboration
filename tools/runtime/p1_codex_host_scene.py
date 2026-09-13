"""Host-owned Temporal dispatch for one committed Codex delivery identity.

The guest only addresses ``CodexHostNodeEndpoint`` through its fixed socket.
This adapter runs behind that endpoint and never accepts native argv or a new
message body. A lost Workflow ACK is resolved against the original Workflow ID.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client

from runtime.codex_driver import (
    AuthorizedOperation,
    CodexAppServerDriver,
)
from runtime.delivery import DeliveryDispatcher
from runtime.delivery_temporal import delivery_worker, submit_delivery
from runtime.node import NodeJournal
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
)
from runtime.receiver_paths import (
    PathSecurityRejected,
    optional_private_file_identity,
    private_parent,
)
from tools.runtime.p1_codex_lifecycle import (
    DECISION_ID,
    TurnBudget,
    project_original_terminal,
    read_codex_scene,
    verify_budget_decision,
)


class HostSceneUncertain(RuntimeError):
    """The original Workflow or native effect needs readback; never re-invoke."""


def _private_run_root(run_id: str) -> Path:
    if os.name != "posix" or os.geteuid() == 0 or not re.fullmatch(r"p1-run-[a-f0-9]{32}", run_id):
        raise HostSceneUncertain("Codex host root requires a non-root exact run ID")
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-codex")
    parent.mkdir(mode=0o700, exist_ok=True)
    try:
        descriptor, _ = private_parent(parent)
        os.close(descriptor)
    except (OSError, PathSecurityRejected) as error:
        raise HostSceneUncertain("Codex host parent is not owner private") from error
    root = parent / run_id
    root.mkdir(mode=0o700)
    for name in ("bin", "codex-home", "cwd", "home", "tmp", "ledger", "observer", "systemd-env"):
        (root / name).mkdir(mode=0o700)
    descriptor, _ = private_parent(root)
    os.close(descriptor)
    return root


def _copy_pinned_native(
    source: Path, destination: Path, expected_sha: str, expected_size: int
) -> None:
    if not source.is_absolute() or not destination.is_absolute():
        raise HostSceneUncertain("Codex native paths must be absolute")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    source_fd = None
    try:
        for part in source.parts[1:-1]:
            following = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            info = os.fstat(following)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in {0, os.geteuid()}
                or stat.S_IMODE(info.st_mode) & 0o002
            ):
                os.close(following)
                raise HostSceneUncertain("Codex native source ancestor is unsafe")
            os.close(directory)
            directory = following
        source_fd = os.open(
            source.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
        original = os.fstat(source_fd)
        if (
            not stat.S_ISREG(original.st_mode)
            or original.st_uid != os.geteuid()
            or original.st_nlink != 1
            or original.st_size != expected_size
        ):
            raise HostSceneUncertain("Codex native source identity differs")
        target_parent, _ = private_parent(destination.parent)
        try:
            temp = ".codex-" + uuid.uuid4().hex
            target_fd = os.open(
                temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=target_parent,
            )
            try:
                digest = hashlib.sha256()
                size = 0
                while block := os.read(source_fd, 1 << 20):
                    size += len(block)
                    digest.update(block)
                    view = memoryview(block)
                    while view:
                        view = view[os.write(target_fd, view) :]
                if size != expected_size or digest.hexdigest() != expected_sha:
                    raise HostSceneUncertain("Codex native source digest differs")
                after = os.fstat(source_fd)
                current = os.stat(source.name, dir_fd=directory, follow_symlinks=False)
                if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                    original.st_dev,
                    original.st_ino,
                    original.st_size,
                    original.st_mtime_ns,
                ) or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                    raise HostSceneUncertain("Codex native source changed during copy")
                os.fchmod(target_fd, 0o500)
                os.fsync(target_fd)
            finally:
                os.close(target_fd)
            os.link(
                temp,
                destination.name,
                src_dir_fd=target_parent,
                dst_dir_fd=target_parent,
                follow_symlinks=False,
            )
            os.unlink(temp, dir_fd=target_parent)
            os.fsync(target_parent)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temp, dir_fd=target_parent)
            raise
        finally:
            os.close(target_parent)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        os.close(directory)


def _verify_key_reference(path: str, expected_path_sha: str) -> tuple[int, int, int, int, int]:
    if hashlib.sha256(path.encode()).hexdigest() != expected_path_sha:
        raise HostSceneUncertain("Codex key reference path pin differs")
    source = Path(path)
    parent = None
    descriptor = None
    try:
        parent, _ = private_parent(source.parent)
        descriptor = os.open(source.name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise HostSceneUncertain("Codex key reference is not owner private")
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)
    except (OSError, PathSecurityRejected) as error:
        raise HostSceneUncertain("Codex key reference is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


class TemporalHostDispatcher:
    """A DeliveryDispatcher facade for the restricted host Node endpoint."""

    def __init__(
        self,
        dispatcher: DeliveryDispatcher,
        *,
        endpoint: str,
        namespace: str,
        task_queue: str,
        deadline: datetime,
    ) -> None:
        if endpoint != "127.0.0.1:7239" or not namespace or not task_queue:
            raise ValueError("host Temporal route is not the pinned loopback provider")
        if deadline.tzinfo is None or deadline <= datetime.now(UTC):
            raise ValueError("host Temporal deadline is invalid")
        self.dispatcher = dispatcher
        self.service = dispatcher.service
        self.endpoint = endpoint
        self.namespace = namespace
        self.task_queue = task_queue
        self.deadline = deadline
        self.last: dict[str, Any] | None = None

    def dispatch(self, identity: dict[str, str]) -> dict[str, Any]:
        if set(identity) != {"tenant_id", "message_id", "operation_id"}:
            raise ValueError("Temporal host dispatch identity is incomplete")
        remaining = (self.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HostSceneUncertain("original Temporal dispatch deadline expired")

        async def original_run():
            client = await Client.connect(self.endpoint, namespace=self.namespace)
            async with delivery_worker(client, self.task_queue, self.dispatcher):
                handle = await submit_delivery(
                    client,
                    self.task_queue,
                    self.dispatcher,
                    identity,
                )
                description = await handle.describe()
                try:
                    result = await asyncio.wait_for(handle.result(), timeout=remaining)
                except TimeoutError as error:
                    raise HostSceneUncertain(
                        "original Temporal Workflow has no bounded result"
                    ) from error
                return result, handle.id, description.run_id

        result, workflow_id, provider_run_id = asyncio.run(original_run())
        if workflow_id != "acs-delivery/" + identity["operation_id"]:
            raise HostSceneUncertain("Temporal Workflow identity differs")
        if not isinstance(result, dict) or result.get("status") not in {
            "delivered",
            "uncertain",
            "blocked",
            "expired",
            "budget_exhausted",
        }:
            raise HostSceneUncertain("original Temporal result is not final")
        self.last = {
            "identity": dict(identity),
            "workflow_id": workflow_id,
            "provider_run_id": provider_run_id,
            "result": dict(result),
        }
        return result


class CodexHostSceneService:
    """One budgeted native turn behind the fixed HostNode dispatch/readback socket."""

    def __init__(
        self,
        host: CodexHostNodeEndpoint,
        node: NodeJournal,
        driver: CodexAppServerDriver,
        adapter,
        temporal: TemporalHostDispatcher,
        *,
        source_tree: str,
        scene_sha256: str,
        budget_path: Path,
        budget_sha256: str,
        artifact_root: Path,
        environment_dir: Path,
        key_reference_path: str | None = None,
        key_reference_path_sha256: str | None = None,
        provider_alias: str,
        model: str,
    ) -> None:
        if (
            host.dispatcher is not temporal
            or temporal.service is not host.dispatcher.service
            or node.node_id != driver.identity.node_id
            or node.boot_incarnation != driver.identity.node_boot_id
            or not re.fullmatch(r"[a-f0-9]{40}", source_tree)
            or not re.fullmatch(r"[a-f0-9]{64}", scene_sha256)
            or not re.fullmatch(r"[a-f0-9]{64}", budget_sha256)
        ):
            raise HostSceneUncertain("Codex host scene components are not one binding")
        self.host, self.node, self.driver, self.adapter = host, node, driver, adapter
        self.temporal = temporal
        self.source_tree = source_tree
        self.scene_sha256 = scene_sha256
        self.budget_path = budget_path
        self.budget_sha256 = budget_sha256
        self.artifact_root = artifact_root
        self.environment_dir = environment_dir
        if (key_reference_path is None) != (key_reference_path_sha256 is None):
            raise HostSceneUncertain("Codex key reference pin is incomplete")
        self.key_reference_path = key_reference_path
        self.key_reference_path_sha256 = key_reference_path_sha256
        self.provider_alias = provider_alias
        self.model = model
        self.key_identity = (
            _verify_key_reference(key_reference_path, key_reference_path_sha256)
            if key_reference_path is not None
            else None
        )
        self.budget = TurnBudget()
        self._attempted = False
        self._dispatch: dict[str, Any] | None = None
        self._projection: dict[str, Any] | None = None
        self._os_proof: dict[str, Any] | None = None
        self._readback: dict[str, Any] | None = None

    def _verify_budget(self) -> None:
        verify_budget_decision(
            self.budget_path,
            self.budget_sha256,
            source_commit=self.host.policy.source_commit,
            source_tree=self.source_tree,
            scene_profile_sha256=self.scene_sha256,
            decision_id=DECISION_ID,
            provider_alias=self.provider_alias,
            model=self.model,
        )
        self._verify_key_pin()

    def _verify_key_pin(self) -> None:
        if self.key_identity is None:
            return
        current = _verify_key_reference(
            self.key_reference_path,
            self.key_reference_path_sha256,
        )
        if current != self.key_identity:
            raise HostSceneUncertain("Codex owner key reference inode changed")

    def _fresh_result(self, request: CodexHostRequest):
        base = self.host.handle(request.model_copy(update={"action": "readback"}))
        if self._dispatch is None or self._projection is None or self._os_proof is None:
            return base
        readback = read_codex_scene(
            self._dispatch,
            self.node,
            self.driver,
            self._projection,
            self.artifact_root,
            source_commit=self.host.policy.source_commit,
            source_tree=self.source_tree,
            run_id=self.host.policy.run_id,
            temporal_endpoint=self.temporal.endpoint,
            temporal_namespace=self.temporal.namespace,
            os_proof=self._os_proof,
            budget=self.budget,
        )
        if self._readback is not None and readback != self._readback:
            raise HostSceneUncertain("Codex host authority readback changed after terminal")
        self._readback = readback
        canonical = json.dumps(
            readback, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return base.model_copy(
            update={
                "scene_readback": readback,
                "scene_readback_sha256": hashlib.sha256(canonical).hexdigest(),
            }
        )

    def handle(self, request: CodexHostRequest):
        if request.action == "readback" or self._readback is not None:
            return self._fresh_result(request)
        if self._attempted:
            raise HostSceneUncertain("original Codex turn is unresolved; no second invoke")
        self._verify_budget()
        self._attempted = True
        started = time.monotonic()
        policy = self.host.policy
        operation = AuthorizedOperation(
            policy.run_id + "-spawn",
            policy.run_id + "-command-spawn",
            policy.run_id + "-message-spawn",
            self.host.dispatcher.service.authority.context.grant_ref,
            policy.deadline,
        )
        self.host.start_native(request, operation)
        try:
            self._verify_key_pin()
            dispatched = self.host.handle(request)
            if dispatched.status != "delivered" or not dispatched.attempt_id:
                raise HostSceneUncertain("original Domain/Temporal dispatch lacks native ACK")
            if self.temporal.last is None:
                raise HostSceneUncertain("original Temporal Workflow/Run is unavailable")
            attempt_id = dispatched.attempt_id
            self._dispatch = {
                "authority": self.host.dispatcher.service.authority,
                "service": self.host.dispatcher.service,
                "endpoint": self.host.dispatcher.service.endpoints[policy.endpoint_id],
                "adapter": self.adapter,
                "identity": {
                    "tenant_id": request.tenant_id,
                    "message_id": request.message_id,
                    "operation_id": request.operation_id,
                },
                "attempt_id": attempt_id,
                "invocation_id": "delivery-invocation:" + attempt_id,
                "dispatch_id": dispatched.dispatch_id,
                "workflow_id": self.temporal.last["workflow_id"],
                "provider_run_id": self.temporal.last["provider_run_id"],
            }
            self._projection = project_original_terminal(
                self._dispatch,
                self.node,
                self.driver,
                self.artifact_root,
                budget=self.budget,
            )
        finally:
            if self.driver.owned is not None:
                try:
                    terminated = self.host.stop_native()
                except Exception as error:
                    raise HostSceneUncertain("Codex host unit termination is unverified") from error
                with self.driver.journal._connect() as connection:
                    rows = connection.execute(
                        "SELECT body FROM driver_events WHERE kind='rpc_dispatch' "
                        "AND operation_id=?",
                        (self._dispatch["invocation_id"] if self._dispatch else "",),
                    ).fetchall()
                starts = sum(json.loads(body).get("method") == "turn/start" for (body,) in rows)
                if not self.environment_dir.is_dir():
                    raise HostSceneUncertain("Codex host EnvironmentFile directory disappeared")
                self._os_proof = {
                    **terminated,
                    "termination_verified": terminated.get("verified") is True,
                    "environment_files_remaining": len(list(self.environment_dir.iterdir())),
                    "model_prompt_count": starts,
                    "elapsed_seconds": max(0.001, time.monotonic() - started),
                    "observed_at": datetime.now(UTC).isoformat(),
                    "usage_tokens": "unknown",
                    "cost_usd": "unknown",
                }
                self._verify_key_pin()
        if self._dispatch is None or self._projection is None:
            raise HostSceneUncertain("Codex original attempt has no terminal projection")
        return self._fresh_result(request)


def _systemctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    uid = os.geteuid()
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
    }
    return subprocess.run(
        ["/usr/bin/systemctl", "--user", "--no-pager", *arguments],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _unit_state(unit: str, run_id: str) -> tuple[str, str, list[int]]:
    if not re.fullmatch(rf"acs-{re.escape(run_id)}-[a-z0-9_.-]+\.service", unit):
        raise HostSceneUncertain("postflight unit is outside the original run")
    response = _systemctl(
        "show",
        unit,
        "--property=Id",
        "--property=ActiveState",
        "--property=LoadState",
        "--property=ControlGroup",
    )
    if response.returncode:
        raise HostSceneUncertain("postflight unit state is unavailable")
    fields = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    if set(fields) != {"Id", "ActiveState", "LoadState", "ControlGroup"} or fields["Id"] != unit:
        raise HostSceneUncertain("postflight unit identity differs")
    group = fields["ControlGroup"]
    if not group:
        if fields["ActiveState"] == "active":
            raise HostSceneUncertain("active postflight unit has no cgroup")
        return fields["ActiveState"], fields["LoadState"], []
    prefix = f"/user.slice/user-{os.geteuid()}.slice/user@{os.geteuid()}.service/"
    if not group.startswith(prefix) or not group.endswith("/" + unit) or ".." in Path(group).parts:
        raise HostSceneUncertain("postflight cgroup left the current user run unit")
    members_path = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
    try:
        info = members_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise HostSceneUncertain("postflight cgroup member file differs")
        members = [int(line) for line in members_path.read_text().splitlines()]
    except FileNotFoundError:
        if fields["ActiveState"] not in {"inactive", "failed"}:
            raise HostSceneUncertain("live postflight cgroup is unavailable") from None
        members = []
    if len(members) > 128 or any(pid <= 0 for pid in members):
        raise HostSceneUncertain("postflight cgroup members exceed bound")
    return fields["ActiveState"], fields["LoadState"], members


def postflight_run(host_root: Path, run_id: str) -> dict[str, Any]:
    """Host runner only: quarantine exact run units after normal or killed host exit."""
    if (
        os.name != "posix"
        or os.geteuid() == 0
        or not re.fullmatch(r"p1-run-[a-f0-9]{32}", run_id)
        or host_root != Path(f"/run/user/{os.geteuid()}/acs-p1-codex") / run_id
    ):
        raise HostSceneUncertain("postflight run root is not the reviewed owner capacity")
    try:
        descriptor, _ = private_parent(host_root)
        os.close(descriptor)
    except (OSError, PathSecurityRejected) as error:
        raise HostSceneUncertain("postflight host root identity is unsafe") from error
    ledger = host_root / "ledger" / "runs.sqlite"
    try:
        identity = optional_private_file_identity(ledger)
    except (OSError, PathSecurityRejected) as error:
        raise HostSceneUncertain("postflight ledger path is unsafe") from error
    boot_state = None
    boot_proof = None
    if identity is not None:
        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT state,proof_json FROM codex_host_boot WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is not None:
            boot_state, encoded = row
            boot_proof = json.loads(encoded) if encoded else None
    response = _systemctl(
        "list-units",
        "--all",
        "--plain",
        "--no-legend",
        f"acs-{run_id}-*.service",
    )
    if response.returncode:
        raise HostSceneUncertain("postflight user manager enumeration failed")
    units = sorted({line.split()[0] for line in response.stdout.splitlines() if line.strip()})
    quarantined = []
    for unit in units:
        active, _load, members = _unit_state(unit, run_id)
        if active == "active" or members:
            stopped = _systemctl("stop", unit)
            if stopped.returncode:
                raise HostSceneUncertain("postflight could not stop original run unit")
            quarantined.append(unit)
        until = time.monotonic() + 10
        while True:
            active, _load, members = _unit_state(unit, run_id)
            if active in {"inactive", "failed"} and members == []:
                break
            if time.monotonic() >= until:
                raise HostSceneUncertain("postflight original cgroup remains live")
            time.sleep(0.05)
    clean_boot = boot_state == "stopped" and (
        isinstance(boot_proof, dict)
        and boot_proof.get("verified") is True
        and boot_proof.get("remaining_pids") == []
    )
    environment_dir = host_root / "systemd-env"
    if environment_dir.is_symlink():
        raise HostSceneUncertain("postflight EnvironmentFile directory changed")
    environment_files = 0
    if environment_dir.exists():
        try:
            descriptor, _ = private_parent(environment_dir)
            try:
                environment_files = len(os.listdir(descriptor))
            finally:
                os.close(descriptor)
        except (OSError, PathSecurityRejected) as error:
            raise HostSceneUncertain("postflight EnvironmentFile directory is unsafe") from error
    return {
        "schema_version": "acs-p1-codex-postflight/1",
        "run_id": run_id,
        "status": "clean"
        if environment_files == 0
        and ((boot_state is None and not units) or (clean_boot and not quarantined))
        else "uncertain",
        "boot_state": boot_state,
        "units_seen": units,
        "quarantined_units": quarantined,
        "remaining_pids": [],
        "environment_files_remaining": environment_files,
        "observed_at": datetime.now(UTC).isoformat(),
    }

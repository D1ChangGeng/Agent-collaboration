"""Build one owner-private OpenCode HostNode capacity from pinned Gate inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime.codex_driver import AuthorizedOperation, BindingIdentity, DriverJournal
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.p1_codex_host_node import CodexHostRunPolicy
from runtime.p1_opencode_host_node import (
    OpenCodeHostNodeEndpoint,
    OpenCodeHostUnixServer,
)
from runtime.receiver_paths import (
    PathSecurityRejected,
    open_validated_file,
    private_parent,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from tools.runtime.p1_codex_host_scene import _copy_pinned_native
from tools.runtime.p1_opencode_auth import PrivateOpenCodeAuth
from tools.runtime.p1_opencode_gate import OpenCodeGateAdmission
from tools.runtime.p1_opencode_host_scene import (
    OpenCodeHostSceneService,
    postflight_opencode_run,
)
from tools.runtime.p1_opencode_temporal import OpenCodeTemporalDispatcher


def _private_run_root(run_id: str) -> Path:
    if os.name != "posix" or os.geteuid() == 0 or not re.fullmatch(
        r"p1-run-[a-f0-9]{32}", run_id
    ):
        raise ValueError("OpenCode host root requires a non-root exact run ID")
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    try:
        descriptor, _ = private_parent(parent)
        os.close(descriptor)
    except (OSError, PathSecurityRejected) as error:
        raise ValueError("OpenCode host parent is not owner private") from error
    root = parent / run_id
    root.mkdir(mode=0o700)
    for name in (
        "bin", "home", "config", "data", "state", "cache", "input",
        "tmp", "ledger", "observer", "systemd-env",
    ):
        (root / name).mkdir(mode=0o700)
    (root / "config" / "opencode").mkdir(mode=0o700)
    descriptor, _ = private_parent(root)
    os.close(descriptor)
    return root


def _write_private(path: Path, data: bytes) -> None:
    parent, _ = private_parent(path.parent)
    try:
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)
    finally:
        os.close(parent)


def clean_unstarted_capacity(root: Path, run_id: str, postgres_dsn: str) -> None:
    """Remove only a never-dispatched run after a clean host postflight."""
    if root != Path(f"/run/user/{os.geteuid()}/acs-p1-opencode") / run_id:
        raise ValueError("OpenCode setup cleanup left exact run root")
    proof = postflight_opencode_run(root, run_id)
    if proof["status"] != "clean" or proof["boot_state"] is not None:
        raise ValueError("OpenCode setup cleanup cannot discard a boot intent")
    schema = "p1_opencode_" + run_id.removeprefix("p1-run-")[:24]
    marker = root / "ledger" / "schema-intent"
    if marker.exists() or marker.is_symlink():
        descriptor, _ = open_validated_file(marker, private=True)
        try:
            if os.read(descriptor, 129) != schema.encode():
                raise ValueError("OpenCode setup schema intent changed")
        finally:
            os.close(descriptor)
        with psycopg.connect(postgres_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            present = admin.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,)
            ).fetchone()[0]
        if present:
            raise ValueError("OpenCode setup schema remains after cleanup")
    descriptor, _ = private_parent(root)
    os.close(descriptor)
    shutil.rmtree(root)


@dataclass
class OpenCodeHostCapacity:
    scene: OpenCodeHostSceneService
    server: OpenCodeHostUnixServer
    supervisor: SystemdUserSupervisor
    driver: OpenCodeNativeDriver
    host_root: Path
    schema: str
    ready: dict[str, Any]
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None
    errors: list[str] | None = None

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("OpenCode host socket already started")
        self.stop_event = threading.Event()
        self.errors = []

        def serve():
            while not self.stop_event.is_set():
                try:
                    self.server.serve_one(accept_timeout=0.25)
                except TimeoutError:
                    continue
                except OSError as error:
                    if not self.stop_event.is_set():
                        self.errors.append(type(error).__name__)
                    break

        self.thread = threading.Thread(target=serve, name="p1-opencode-host-node", daemon=True)
        self.thread.start()

    def close(self) -> dict[str, Any]:
        if self.stop_event is not None:
            self.stop_event.set()
        self.server.close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        unresolved = bool(self.thread and self.thread.is_alive()) or bool(self.errors)
        if self.driver.owned is not None and self.driver.owned.process.poll() is None:
            try:
                self.scene.host.stop_native()
                self.driver.detach_transport()
            except Exception:  # noqa: BLE001 -- cleanup uncertainty reaches postflight
                unresolved = True
        try:
            self.supervisor.close()
        except Exception:  # noqa: BLE001 -- cleanup uncertainty reaches postflight
            unresolved = True
        proof = postflight_opencode_run(self.host_root, self.scene.host.policy.run_id)
        if unresolved:
            proof["status"] = "uncertain"
        return proof


def prepare_opencode_host_capacity(
    loopback: dict[str, Any],
    *,
    scene_path: Path,
    scene_sha256: str,
    budget_path: Path,
    budget_sha256: str,
    run_id: str,
    source_commit: str,
    source_tree: str,
    machine_id: str,
    node_id: str,
    source_snapshot: Path,
    plan_expires_at: datetime,
) -> OpenCodeHostCapacity:
    if (
        not re.fullmatch(r"[a-f0-9]{40}", source_commit)
        or not re.fullmatch(r"[a-f0-9]{40}", source_tree)
        or not machine_id or node_id != loopback.get("node_id")
        or loopback.get("temporal_endpoint") != "127.0.0.1:7239"
        or not loopback.get("temporal_namespace")
        or plan_expires_at.tzinfo is None
    ):
        raise ValueError("OpenCode host runtime identity is incomplete")
    connection = conninfo_to_dict(loopback.get("postgres_dsn", ""))
    if (
        connection.get("host"), connection.get("port"), connection.get("dbname")
    ) != ("127.0.0.1", "54329", "temporal") or not connection.get("password"):
        raise ValueError("OpenCode host PostgreSQL route differs")
    admission = OpenCodeGateAdmission.load(
        scene_path, scene_sha256, budget_path, budget_sha256,
        source_commit=source_commit, source_tree=source_tree,
    ).bind_run(run_id, machine_id, node_id)
    admission.key_reference_identity()
    root = _private_run_root(run_id)
    scene = admission.scene
    _copy_pinned_native(
        Path(scene["native_executable_path"]), root / "bin" / "opencode",
        scene["native_executable_sha256"], scene["native_executable_size"],
    )
    config_path = root / "config" / "opencode" / "opencode.json"
    _write_private(config_path, admission.config_template_bytes())
    schema_file = (
        source_snapshot / "runtime_tests/schema-1.18.30/opencode-openapi.json"
    )
    if (
        not schema_file.is_file() or schema_file.is_symlink()
        or hashlib.sha256(schema_file.read_bytes()).hexdigest() != scene["schema_sha256"]
    ):
        raise ValueError("OpenCode reviewed source schema differs")
    suffix = run_id.removeprefix("p1-run-")[:24]
    schema = "p1_opencode_" + suffix
    _write_private(root / "ledger" / "schema-intent", schema.encode())
    with psycopg.connect(loopback["postgres_dsn"], autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    _write_private(root / "ledger" / "schema-created", schema.encode())
    scoped_dsn = make_conninfo(loopback["postgres_dsn"], options=f"-c search_path={schema}")
    authority = DomainAuthority(scoped_dsn)
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "delivery.manage", "message.send", "message.read",
        "runtime.invoke",
    ))
    with authority._connect() as database:
        scope_policy = database.execute(
            "SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id='local-scope'",
            (authority.tenant_id,),
        ).fetchone()[0]
    deadline = min(datetime.now(UTC) + timedelta(seconds=120), plan_expires_at)
    if deadline <= datetime.now(UTC):
        raise ValueError("OpenCode host plan deadline expired")
    boot = "boot-" + suffix
    prior_umask = os.umask(0o077)
    try:
        node = NodeJournal(
            root / "ledger" / "node.sqlite",
            machine_id=machine_id, node_id=node_id, boot_incarnation=boot,
        )
        journal = DriverJournal(root / "ledger" / "driver.sqlite")
    finally:
        os.umask(prior_umask)
    binding = BindingIdentity(
        node_id, boot, "p1-opencode-runtime", "p1-opencode-execution-" + suffix,
        "local-slot", 1,
    )
    profile = OpenCodeLaunchProfile(
        str(root / "bin" / "opencode"), scene["native_executable_sha256"],
        "1.18.30", str(schema_file), scene["schema_sha256"],
        str(root / "input"), str(root / "home"), str(root / "config"),
        str(root / "data"), str(root / "state"), str(root / "cache"),
        str(root / "tmp"), scene["config_sha256"], scene["agent"],
        scene["provider_id"], scene["model_id"],
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    profile.validate(fresh=True)
    auth_stager = PrivateOpenCodeAuth(admission)
    supervisor = SystemdUserSupervisor(
        tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
        termination_timeout=10, environment_directory=root / "systemd-env",
    )
    scope_sha = hashlib.sha256(
        json.dumps(scope_policy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    def current(operation: AuthorizedOperation, observed: BindingIdentity) -> None:
        if observed != binding or operation.grant_ref != authority.context.grant_ref:
            raise ValueError("OpenCode Driver left current Node/Grant identity")
        if operation.operation_id == run_id + "-spawn":
            # The HostNode outer transaction owns the Grant and Scope rows.
            return
        if not operation.operation_id.startswith("delivery-invocation:"):
            raise ValueError("OpenCode Driver operation is outside original attempt")
        attempt_id = operation.operation_id.removeprefix("delivery-invocation:")
        with authority._connect() as database, database.cursor() as cursor:
            cursor.execute(
                "SELECT m.command_id,m.message_id,m.deadline,m.command_json "
                "FROM delivery_attempts a JOIN delivery_messages m "
                "ON m.tenant_id=a.tenant_id AND m.message_id=a.message_id "
                "WHERE a.tenant_id=%s AND a.attempt_id=%s",
                (authority.tenant_id, attempt_id),
            )
            row = cursor.fetchone()
            if (
                row is None or row[0:2] != (operation.command_id, operation.message_id)
                or operation.deadline > row[2]
            ):
                raise ValueError("OpenCode Driver attempt is not current in PostgreSQL")
            command = CommandEnvelope.model_validate_json(
                json.dumps(row[3], default=str), strict=True
            )
            try:
                authority._authorize(command, cursor, "runtime.invoke", "local-scope")
            except AuthorizationDenied as error:
                raise ValueError("OpenCode Driver current authority was revoked") from error
            cursor.execute(
                "SELECT policy,status FROM scopes WHERE tenant_id=%s "
                "AND scope_id='local-scope'",
                (authority.tenant_id,),
            )
            scope = cursor.fetchone()
            cursor.execute(
                "SELECT status FROM agent_slots WHERE tenant_id=%s "
                "AND scope_id='local-scope' AND agent_slot_id='local-slot'",
                (authority.tenant_id,),
            )
            slot = cursor.fetchone()
            if (
                scope is None or scope[1] != "active" or slot != ("active",)
                or hashlib.sha256(
                    json.dumps(scope[0], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest() != scope_sha
            ):
                raise ValueError("OpenCode Driver Scope/Policy/Slot is no longer current")

    driver = OpenCodeNativeDriver(
        run_id + "-binding", profile, journal,
        identity=binding, check_current=current, supervisor=supervisor,
        http_timeout=10, readback_attempts=6, auth_stager=auth_stager,
        required_provider_url=scene["provider_url"],
    )

    def authorize(invocation: Any, observed: BindingIdentity) -> AuthorizedOperation:
        if observed != binding or invocation.envelope.grant_ref != authority.context.grant_ref:
            raise ValueError("OpenCode native invocation left current binding")
        return AuthorizedOperation(
            invocation.invocation_id, invocation.command_id, invocation.message_id,
            invocation.envelope.grant_ref, invocation.envelope.packet.deadline,
        )

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize)
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", adapter)
    endpoint_id = "opencode-endpoint-" + suffix
    delivery = DeliveryService(authority, {endpoint_id: endpoint})
    issued = datetime.now(UTC)
    bind_command = CommandEnvelope(
        command_id=run_id + "-endpoint-bind",
        idempotency_key=run_id + "-endpoint-bind-key", correlation_id=run_id,
        command_type="message.bind", tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref,
        grant_ref=authority.context.grant_ref,
        target_kind="message", target_id=endpoint_id, expected_revision=0,
        issued_at=issued, deadline=deadline,
    )
    delivery.bind_endpoint(
        bind_command,
        EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="local-slot", expires_at=deadline,
        ),
    )
    policy = CodexHostRunPolicy(
        run_id=run_id, tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        scope_id="local-scope", agent_slot_id="local-slot",
        scope_policy_sha256=scope_sha, endpoint_id=endpoint_id,
        source_commit=source_commit, native_sha256=scene["native_executable_sha256"],
        config_sha256=scene["config_sha256"], deadline=deadline,
    )
    temporal = OpenCodeTemporalDispatcher(
        DeliveryDispatcher(delivery), endpoint="127.0.0.1:7239",
        namespace=loopback["temporal_namespace"],
        task_queue="p1-opencode-" + suffix, deadline=deadline,
    )
    host = OpenCodeHostNodeEndpoint(
        policy, temporal, root / "ledger" / "host.sqlite",
        native_path=root / "bin" / "opencode", config_path=config_path,
    )
    scene_service = OpenCodeHostSceneService(
        host, node, driver, adapter, temporal, admission,
        scene_path=scene_path, budget_path=budget_path,
        artifact_root=root / "ledger" / "artifacts",
        environment_dir=root / "systemd-env",
        temporal_namespace=loopback["temporal_namespace"],
    )
    server = OpenCodeHostUnixServer(scene_service, root / "observer" / "host.sock")
    ready = {
        "schema_version": "acs-p1-opencode-host-ready/1",
        "run_id": run_id, "schema": schema,
        "endpoint_id": endpoint_id, "endpoint_descriptor": endpoint.descriptor(),
        "binding_revision": 1, "node_id": node_id, "machine_id": machine_id,
        "boot_incarnation": boot, "source_commit": source_commit,
        "source_tree": source_tree, "scene_sha256": scene_sha256,
        "budget_sha256": budget_sha256, "config_sha256": scene["config_sha256"],
        "native_sha256": scene["native_executable_sha256"],
        "deadline": deadline.isoformat(),
    }
    _write_private(
        root / "observer" / "ready.json",
        (json.dumps(ready, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    return OpenCodeHostCapacity(
        scene_service, server, supervisor, driver, root, schema, ready,
    )

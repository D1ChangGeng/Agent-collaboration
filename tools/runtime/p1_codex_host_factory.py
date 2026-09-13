"""Construct one restricted host-owned Codex scene from pinned Gate inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRunPolicy,
    CodexHostUnixServer,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from tools.runtime.p1_codex_host_scene import (
    CodexHostSceneService,
    HostSceneUncertain,
    TemporalHostDispatcher,
    _copy_pinned_native,
    _private_run_root,
    _verify_key_reference,
    postflight_run,
)
from tools.runtime.p1_codex_lifecycle import (
    DECISION_ID,
    stage_codex_home,
    validate_scene_profile,
    verify_budget_decision,
)


@dataclass
class CodexHostCapacity:
    scene: CodexHostSceneService
    server: CodexHostUnixServer
    supervisor: SystemdUserSupervisor
    driver: CodexAppServerDriver
    host_root: Path
    schema: str
    ready: dict[str, Any]
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None
    errors: list[str] | None = None

    def start(self) -> None:
        if self.thread is not None:
            raise HostSceneUncertain("Codex host socket already started")
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

        self.thread = threading.Thread(target=serve, name="p1-codex-host-node", daemon=True)
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
            except Exception:  # noqa: BLE001 -- cleanup uncertainty must reach postflight
                unresolved = True
        try:
            self.supervisor.close()
        except Exception:  # noqa: BLE001 -- cleanup uncertainty must reach postflight
            unresolved = True
        proof = postflight_run(self.host_root, self.scene.host.policy.run_id)
        if unresolved:
            proof["status"] = "uncertain"
        return proof


def prepare_codex_host_capacity(
    loopback: dict[str, Any],
    scene_profile: dict[str, Any],
    *,
    run_id: str,
    source_commit: str,
    source_tree: str,
    machine_id: str,
    source_snapshot: Path,
    scene_sha256: str,
    budget_path: Path,
    budget_sha256: str,
    plan_expires_at: datetime,
) -> CodexHostCapacity:
    scene = validate_scene_profile(scene_profile)
    if (
        not re.fullmatch(r"[a-f0-9]{40}", source_commit)
        or not re.fullmatch(r"[a-f0-9]{40}", source_tree)
        or not machine_id
        or loopback.get("temporal_endpoint") != "127.0.0.1:7239"
        or not loopback.get("temporal_namespace")
        or not loopback.get("node_id")
        or plan_expires_at.tzinfo is None
    ):
        raise HostSceneUncertain("Codex host runtime identity is incomplete")
    connection = conninfo_to_dict(loopback.get("postgres_dsn", ""))
    if (connection.get("host"), connection.get("port"), connection.get("dbname")) != (
        "127.0.0.1",
        "54329",
        "temporal",
    ) or not connection.get("password"):
        raise HostSceneUncertain("Codex host PostgreSQL route differs")
    verify_budget_decision(
        budget_path,
        budget_sha256,
        source_commit=source_commit,
        source_tree=source_tree,
        scene_profile_sha256=scene_sha256,
        decision_id=DECISION_ID,
        provider_alias=scene["provider_alias"],
        model=scene["model"],
    )
    _verify_key_reference(scene["auth_key_ref_path"], scene["auth_key_ref_path_sha256"])
    root = _private_run_root(run_id)
    _copy_pinned_native(
        Path(scene["native_executable_path"]),
        root / "bin" / "codex",
        scene["native_executable_sha256"],
        scene["native_executable_size"],
    )
    staged = stage_codex_home(root, scene)
    schema_file = (
        source_snapshot / "runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json"
    )
    if (
        not schema_file.is_file()
        or schema_file.is_symlink()
        or hashlib.sha256(schema_file.read_bytes()).hexdigest() != scene["schema_sha256"]
    ):
        raise HostSceneUncertain("Codex reviewed source schema differs")
    suffix = run_id.removeprefix("p1-run-")[:24]
    schema = "p1_codex_" + suffix
    with psycopg.connect(loopback["postgres_dsn"], autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(loopback["postgres_dsn"], options=f"-c search_path={schema}")
    authority = DomainAuthority(scoped_dsn)
    authority.initialize()
    authority.bootstrap_local_grant(
        (
            "work_item.create",
            "delivery.manage",
            "message.send",
            "message.read",
            "runtime.invoke",
        )
    )
    with authority._connect() as database:
        scope_policy = database.execute(
            "SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id='local-scope'",
            (authority.tenant_id,),
        ).fetchone()[0]
    deadline = min(datetime.now(UTC) + timedelta(seconds=120), plan_expires_at)
    if deadline <= datetime.now(UTC):
        raise HostSceneUncertain("Codex host plan deadline expired")
    boot = "boot-" + suffix
    prior_umask = os.umask(0o077)
    try:
        node = NodeJournal(
            root / "ledger" / "node.sqlite",
            machine_id=machine_id,
            node_id=loopback["node_id"],
            boot_incarnation=boot,
        )
        journal = DriverJournal(root / "ledger" / "driver.sqlite")
    finally:
        os.umask(prior_umask)
    binding = BindingIdentity(
        loopback["node_id"],
        boot,
        "p1-codex-runtime",
        "p1-codex-execution-" + suffix,
        "local-slot",
        1,
    )
    config_path = Path(staged["config"])
    profile = LaunchProfile(
        staged["executable"],
        scene["native_executable_sha256"],
        "0.153.2",
        str(schema_file),
        scene["schema_sha256"],
        staged["cwd"],
        str(root / "codex-home"),
        hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "achp-engineer",
        {
            "PATH": "/opt/acs/codex-sandbox/bin:/usr/bin:/bin",
            "HOME": staged["home"],
            "TMPDIR": staged["tmp"],
            "LANG": "C.UTF-8",
        },
        scene["model"],
    )
    profile.validate()
    supervisor = SystemdUserSupervisor(
        tasks_max=64,
        memory_max=1_073_741_824,
        cpu_quota_percent=100,
        termination_timeout=10,
        environment_directory=root / "systemd-env",
    )

    def current(operation: AuthorizedOperation, observed: BindingIdentity) -> None:
        if observed != binding or operation.grant_ref != authority.context.grant_ref:
            raise HostSceneUncertain("Codex Driver left current Node/Grant identity")
        with authority._connect() as database, database.cursor() as cursor:
            if operation.operation_id == run_id + "-spawn":
                # The HostNode outer transaction already owns the command and
                # Grant locks through process birth for this synthetic operation.
                return
            if not operation.operation_id.startswith("delivery-invocation:"):
                raise HostSceneUncertain("Codex Driver operation is outside original attempt")
            attempt_id = operation.operation_id.removeprefix("delivery-invocation:")
            cursor.execute(
                "SELECT m.command_id,m.message_id,m.deadline,m.command_json "
                "FROM delivery_attempts a "
                "JOIN delivery_messages m ON m.tenant_id=a.tenant_id "
                "AND m.message_id=a.message_id WHERE a.tenant_id=%s AND a.attempt_id=%s",
                (authority.tenant_id, attempt_id),
            )
            row = cursor.fetchone()
            if (
                row is None
                or row[0:2] != (operation.command_id, operation.message_id)
                or operation.deadline > row[2]
            ):
                raise HostSceneUncertain("Codex Driver attempt is not current in PostgreSQL")
            command = CommandEnvelope.model_validate_json(
                json.dumps(row[3], default=str), strict=True
            )
            try:
                authority._authorize(command, cursor, "runtime.invoke", "local-scope")
            except AuthorizationDenied as error:
                raise HostSceneUncertain("Codex Driver current authority was revoked") from error
            cursor.execute(
                "SELECT revoked_at,expires_at,principal_ref,permissions,clock_timestamp() "
                "FROM grants WHERE grant_ref=%s FOR UPDATE",
                (operation.grant_ref,),
            )
            grant = cursor.fetchone()
            if (
                grant is None
                or grant[0] is not None
                or grant[1] <= grant[4]
                or grant[2] != authority.context.principal_ref
                or "runtime.invoke" not in grant[3]
            ):
                raise HostSceneUncertain("Codex Driver Grant is no longer current")
            cursor.execute(
                "SELECT policy,status FROM scopes WHERE tenant_id=%s AND scope_id='local-scope'",
                (authority.tenant_id,),
            )
            scope = cursor.fetchone()
            cursor.execute(
                "SELECT status FROM agent_slots WHERE tenant_id=%s AND scope_id='local-scope' "
                "AND agent_slot_id='local-slot'",
                (authority.tenant_id,),
            )
            slot = cursor.fetchone()
            if (
                scope is None
                or scope[1] != "active"
                or hashlib.sha256(
                    json.dumps(scope[0], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest() != policy.scope_policy_sha256
                or slot != ("active",)
            ):
                raise HostSceneUncertain("Codex Driver Scope/Policy/Slot is no longer current")

    driver = CodexAppServerDriver(
        run_id + "-binding",
        profile,
        journal,
        identity=binding,
        check_current=current,
        supervisor=supervisor,
        rpc_timeout=30,
    )

    def authorize(invocation, observed):
        if observed != binding or invocation.envelope.grant_ref != authority.context.grant_ref:
            raise HostSceneUncertain("Codex native invocation left current binding")
        return AuthorizedOperation(
            invocation.invocation_id,
            invocation.command_id,
            invocation.message_id,
            invocation.envelope.grant_ref,
            invocation.envelope.packet.deadline,
        )

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize)
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", adapter)
    endpoint_id = "codex-endpoint-" + suffix
    delivery = DeliveryService(authority, {endpoint_id: endpoint})
    issued = datetime.now(UTC)
    bind_command = CommandEnvelope(
        command_id=run_id + "-endpoint-bind",
        idempotency_key=run_id + "-endpoint-bind-key",
        correlation_id=run_id,
        command_type="message.bind",
        tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref,
        grant_ref=authority.context.grant_ref,
        target_kind="message",
        target_id=endpoint_id,
        expected_revision=0,
        issued_at=issued,
        deadline=deadline,
    )
    delivery.bind_endpoint(
        bind_command,
        EndpointBindingRequest(
            scope_id="local-scope",
            agent_slot_id="local-slot",
            expires_at=deadline,
        ),
    )
    policy = CodexHostRunPolicy(
        run_id=run_id,
        tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        scope_id="local-scope",
        agent_slot_id="local-slot",
        scope_policy_sha256=hashlib.sha256(
            json.dumps(scope_policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        endpoint_id=endpoint_id,
        source_commit=source_commit,
        native_sha256=scene["native_executable_sha256"],
        config_sha256=profile.config_sha256,
        deadline=deadline,
    )
    temporal = TemporalHostDispatcher(
        DeliveryDispatcher(delivery),
        endpoint="127.0.0.1:7239",
        namespace=loopback["temporal_namespace"],
        task_queue="p1-codex-" + suffix,
        deadline=deadline,
    )
    host = CodexHostNodeEndpoint(
        policy,
        temporal,
        root / "ledger" / "runs.sqlite",
        native_path=root / "bin" / "codex",
        config_path=config_path,
    )
    scene_service = CodexHostSceneService(
        host,
        node,
        driver,
        adapter,
        temporal,
        source_tree=source_tree,
        scene_sha256=scene_sha256,
        budget_path=budget_path,
        budget_sha256=budget_sha256,
        artifact_root=root / "ledger" / "artifacts",
        environment_dir=root / "systemd-env",
        key_reference_path=scene["auth_key_ref_path"],
        key_reference_path_sha256=scene["auth_key_ref_path_sha256"],
        provider_alias=scene["provider_alias"],
        model=scene["model"],
    )
    server = CodexHostUnixServer(scene_service, root / "observer" / "host.sock")
    ready = {
        "schema_version": "acs-p1-codex-host-ready/1",
        "run_id": run_id,
        "schema": schema,
        "endpoint_id": endpoint_id,
        "endpoint_descriptor": endpoint.descriptor(),
        "binding_revision": 1,
        "node_id": loopback["node_id"],
        "machine_id": machine_id,
        "boot_incarnation": boot,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "scene_sha256": scene_sha256,
        "budget_sha256": budget_sha256,
        "config_sha256": profile.config_sha256,
        "deadline": deadline.isoformat(),
    }
    ready_path = root / "observer" / "ready.json"
    descriptor = os.open(ready_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        data = (json.dumps(ready, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return CodexHostCapacity(scene_service, server, supervisor, driver, root, schema, ready)

"""Actual Codex 0.153.2 ELF bootstrap under the restricted host Node, no turn."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
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
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
    CodexHostRunPolicy,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_tests.test_delivery import command, query

pytest_plugins = ("runtime_tests.test_delivery",)

NATIVE_SHA256 = "f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c"
NATIVE_SIZE = 258_597_984
CATALOG_SHA256 = "c3172f5fa1a69329d1aba8ca6328baf08b07927a100ce67c7d18d4c3d7ac1592"
SOURCE_COMMIT = "d9d7d957421fd184ca3f9ef53d6ecb5bb8cea170"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def test_actual_codex_binary_starts_and_stops_without_model_turn(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("actual no-model bootstrap requires non-root Linux")
    source_native = Path(os.environ.get("ACS_P1_CODEX_NATIVE_PATH", ""))
    source_catalog = Path(os.environ.get("ACS_P1_CODEX_CATALOG_PATH", ""))
    if not source_native.is_file() or not source_catalog.is_file():
        pytest.skip("reviewed Codex native/catalog paths were not supplied")
    assert source_native.stat().st_size == NATIVE_SIZE and _sha(source_native) == NATIVE_SHA256
    assert _sha(source_catalog) == CATALOG_SHA256
    private = tmp_path / "actual-codex-host"
    private.mkdir(mode=0o700)
    native = private / "codex"
    shutil.copyfile(source_native, native)
    native.chmod(0o500)
    assert native.stat().st_size == NATIVE_SIZE and _sha(native) == NATIVE_SHA256
    codex_home = private / "codex-home"
    codex_home.mkdir(mode=0o700)
    cwd = private / "cwd"
    cwd.mkdir(mode=0o700)
    private_home = private / "home"
    private_home.mkdir(mode=0o700)
    temp = private / "tmp"
    temp.mkdir(mode=0o700)
    catalog = codex_home / "models.json"
    shutil.copyfile(source_catalog, catalog)
    catalog.chmod(0o600)
    assert _sha(catalog) == CATALOG_SHA256
    schema = (
        Path(__file__).parents[3]
        / "runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json"
    )
    config = codex_home / "config.toml"
    config.write_text(
        "\n".join(
            (
                'model = "gpt-5.6-sol"',
                'model_reasoning_effort = "low"',
                'model_provider = "fixture-provider"',
                f'model_catalog_json = "{catalog}"',
                'approval_policy = "never"',
                'default_permissions = "achp-engineer"',
                "allow_login_shell = false",
                'web_search = "disabled"',
                "[features]",
                "multi_agent = false",
                "multi_agent_v2 = false",
                "shell_tool = false",
                "request_permissions_tool = false",
                "apps = false",
                "plugins = false",
                "recommended_plugins = false",
                "[permissions.achp-engineer.filesystem]",
                '":minimal" = "read"',
                f'"{cwd}" = "read"',
                "[model_providers.fixture-provider]",
                'name = "P1 no-model bootstrap"',
                'base_url = "https://provider.example.invalid/v1"',
                'wire_api = "responses"',
                "[model_providers.fixture-provider.auth]",
                'command = "/usr/bin/cat"',
                f'args = ["{private / "missing-no-model-key"}"]',
                "timeout_ms = 5000",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    run_id = "p1-run-" + uuid.uuid4().hex
    scope_policy = query(setup, "SELECT policy FROM scopes WHERE scope_id='local-scope'")[0][0]
    policy = CodexHostRunPolicy(
        run_id=run_id,
        tenant_id=setup.authority.tenant_id,
        authority_id=setup.authority.context.authority_id,
        authority_incarnation=setup.authority.context.authority_incarnation,
        scope_id="local-scope",
        agent_slot_id="local-slot",
        scope_policy_sha256=hashlib.sha256(
            json.dumps(scope_policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        endpoint_id="endpoint",
        source_commit=SOURCE_COMMIT,
        native_sha256=NATIVE_SHA256,
        config_sha256=_sha(config),
        deadline=datetime.now(UTC) + timedelta(seconds=90),
    )
    setup.authority.create_work_item(
        command(setup.authority, "work_item.create", "work-codex-native"),
        "local-scope",
        "local-slot",
        SOURCE_COMMIT,
    )
    binding = BindingIdentity(
        setup.journal.node_id,
        setup.journal.boot_incarnation,
        "runtime-codex-native",
        "execution-codex-native",
        "local-slot",
        2,
    )
    profile = LaunchProfile(
        str(native),
        NATIVE_SHA256,
        "0.153.2",
        str(schema),
        _sha(schema),
        str(cwd),
        str(codex_home),
        _sha(config),
        "achp-engineer",
        {
            "PATH": "/opt/acs/codex-sandbox/bin:/usr/bin:/bin",
            "HOME": str(private_home),
            "TMPDIR": str(temp),
            "LANG": "C.UTF-8",
        },
        "gpt-5.6-sol",
    )
    supervisor = SystemdUserSupervisor(
        tasks_max=64,
        memory_max=1_073_741_824,
        cpu_quota_percent=100,
        termination_timeout=10,
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

    driver = CodexAppServerDriver(
        run_id + "-binding",
        profile,
        DriverJournal(private / "driver.sqlite"),
        identity=binding,
        check_current=current,
        supervisor=supervisor,
        rpc_timeout=15,
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
    host = CodexHostNodeEndpoint(
        policy,
        DeliveryDispatcher(setup.service),
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
    )
    message_id = "message-" + uuid.uuid4().hex
    issued = command(setup.authority, "message.send", message_id, correlation_id=run_id)
    packet = DeliveryPacket(
        work_item_id="work-codex-native",
        target_scope_id="local-scope",
        target_agent_slot_id="local-slot",
        accepted_revision=0,
        goal="Observe no-model Codex startup",
        accepted_state_summary="revision zero",
        request="No model turn",
        source_baseline=SOURCE_COMMIT,
        expected_response="no-model process lifecycle",
        activation="invoke",
        deadline=datetime.now(UTC) + timedelta(seconds=85),
        maximum_attempts=1,
    )
    sent = setup.service.send_message(issued, packet, endpoint_id="endpoint", binding_revision=2)
    request = CodexHostRequest(
        action="dispatch",
        run_id=run_id,
        tenant_id=policy.tenant_id,
        message_id=message_id,
        command_id=issued.command_id,
        operation_id=sent.operation_id,
        endpoint_id="endpoint",
        source_commit=SOURCE_COMMIT,
        native_sha256=NATIVE_SHA256,
        config_sha256=policy.config_sha256,
    )
    spawn = AuthorizedOperation(
        run_id + "-spawn",
        run_id + "-command-spawn",
        run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        policy.deadline,
    )
    try:
        boot = host.start_native(request, spawn)
        assert boot["verified"] and run_id in boot["unit"]
        assert driver.thread_id and driver.session_id
        with driver.journal._connect() as connection:
            turns = connection.execute(
                "SELECT count(*) FROM driver_events WHERE kind='rpc_dispatch' "
                "AND body LIKE '%turn/start%'"
            ).fetchone()[0]
        assert turns == 0
        assert host.stop_native()["remaining_pids"] == []
    finally:
        supervisor.close()
        driver.detach_transport()
        native.unlink(missing_ok=True)

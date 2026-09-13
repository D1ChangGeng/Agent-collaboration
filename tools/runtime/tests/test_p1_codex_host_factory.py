"""Construct a private host capacity with a no-model executable and fixed socket."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from runtime.delivery_models import DeliveryPacket
from runtime.models import CommandEnvelope
from runtime.p1_codex_host_node import CodexHostRequest
from tools.runtime import p1_codex_lifecycle as lifecycle
from tools.runtime.p1_codex_host_factory import prepare_codex_host_capacity
from tools.runtime.p1_codex_lifecycle import DECISION_ID, MODEL_PROMPT, read_codex_layer


@pytest.mark.skipif(sys.platform != "linux", reason="private host capacity requires Linux")
@pytest.mark.parametrize("current_change", [None, "grant_permissions", "scope_policy", "slot"])
def test_private_host_factory_stages_no_model_binary_and_no_general_command_socket(
    current_change, monkeypatch
):
    if os.geteuid() == 0 or not os.getenv("ACS_P1_DSN"):
        pytest.skip("non-root PostgreSQL fixture required")
    source = Path(f"/run/user/{os.geteuid()}/acs-p1-codex-source")
    source.mkdir(mode=0o700, exist_ok=True)
    suffix = uuid.uuid4().hex
    fixture_root = source / suffix
    fixture_root.mkdir(mode=0o700)
    native = fixture_root / "codex"
    raw = (Path(__file__).parents[3] / "runtime_tests/p1_codex_stdio_fixture.py").read_bytes()
    assert raw.startswith(b"#!/usr/bin/env python3\n")
    native.write_bytes(raw + b"\n#" + b"x" * (1_000_000 - len(raw) - 2))
    native.chmod(0o500)
    catalog = fixture_root / "models.json"
    catalog.write_text(json.dumps({"models": [{
        "slug": "gpt-5.6-sol",
        "experimental_supported_tools": [],
        "supported_reasoning_levels": [{"effort": "low"}],
        "display_name": "Fixture",
        "description": "fixture" * 200,
    }]}), encoding="utf-8")
    catalog.chmod(0o600)
    key = fixture_root / "empty-no-model-key"
    key.write_bytes(b"")
    key.chmod(0o600)
    schema_file = Path(__file__).parents[3] / (
        "runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json"
    )
    run_id = "p1-run-" + uuid.uuid4().hex
    scene = {
        "schema_version": "acs-p1-codex-scene/1",
        "native_executable_path": str(native),
        "native_executable_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "native_executable_size": native.stat().st_size,
        "codex_version": "0.153.2",
        "schema_sha256": hashlib.sha256(schema_file.read_bytes()).hexdigest(),
        "provider_alias": "fixture-provider",
        "provider_url": "https://provider.example.invalid/v1",
        "wire_api": "responses",
        "auth_command": "/usr/bin/cat",
        "auth_key_ref_path": str(key),
        "auth_key_ref_path_sha256": hashlib.sha256(str(key).encode()).hexdigest(),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "low",
        "model_catalog_entry": {"slug": "gpt-5.6-sol", "experimental_supported_tools": []},
        "model_catalog_path": str(catalog),
        "model_catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
        "model_catalog_size": catalog.stat().st_size,
        "max_turn_starts": 1,
        "max_collect_reads": 6,
        "max_elapsed_seconds": 120,
        "budget_evidence_ref": DECISION_ID,
    }
    scene_raw = json.dumps(scene, sort_keys=True).encode()
    scene_sha = hashlib.sha256(scene_raw).hexdigest()
    budget = fixture_root / "budget.json"
    budget.write_text(
        json.dumps(
            {
                "schema_version": "acs-p1-model-request-budget/1",
                "decision_id": DECISION_ID,
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "scene_profile_sha256": scene_sha,
                "scenario_id": "P1-CODEX-LIFECYCLE",
                "provider_alias": "fixture-provider",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "low",
                "prompt": MODEL_PROMPT,
                "max_turn_starts": 1,
                "max_collect_reads": 6,
                "max_elapsed_seconds": 120,
                "retry_policy": "No second turn/start after uncertainty.",
                "spend_status": "Provider monetary cap not observed; cost unknown.",
                "tool_policy": "No tool invocation or delegation.",
            }
        ),
        encoding="utf-8",
    )
    budget.chmod(0o600)
    capacity = None
    closed = False
    try:
        capacity = prepare_codex_host_capacity(
            {
                "postgres_dsn": os.environ["ACS_P1_DSN"],
                "temporal_endpoint": "127.0.0.1:7239",
                "temporal_namespace": "default",
                "node_id": "fixture-node",
            },
            scene,
            run_id=run_id,
            source_commit="a" * 40,
            source_tree="b" * 40,
            machine_id="fixture-machine",
            source_snapshot=Path(__file__).parents[3],
            scene_sha256=scene_sha,
            budget_path=budget,
            budget_sha256=hashlib.sha256(budget.read_bytes()).hexdigest(),
            plan_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert capacity.ready["run_id"] == run_id
        assert capacity.ready["schema"].startswith("p1_codex_")
        assert capacity.host_root.joinpath("bin/codex").stat().st_size == 1_000_000
        assert stat.S_IMODE(capacity.host_root.joinpath("bin/codex").stat().st_mode) == 0o500
        capacity.start()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(capacity.server.socket_path))
            client.sendall(
                b'{"schema_version":"acs-p1-codex-host-request/1",'
                b'"action":"shell","argv":["systemd-run"]}\n'
            )
            refused = json.loads(client.recv(4096))
        assert refused == {"schema_version": "acs-p1-codex-host-error/1", "state": "rejected"}
        authority = capacity.scene.host.dispatcher.service.authority
        service = capacity.scene.host.dispatcher.service
        deadline = capacity.scene.host.policy.deadline

        def command(kind, target, target_kind):
            identity = uuid.uuid4().hex
            return CommandEnvelope(
                command_id="p1-fixture-" + identity,
                idempotency_key="p1-fixture-key-" + identity,
                correlation_id=run_id,
                command_type=kind,
                tenant_id=authority.tenant_id,
                authority_id=authority.context.authority_id,
                authority_incarnation=authority.context.authority_incarnation,
                principal_ref=authority.context.principal_ref,
                grant_ref=authority.context.grant_ref,
                target_kind=target_kind,
                target_id=target,
                expected_revision=0,
                issued_at=datetime.now(UTC),
                deadline=deadline,
            )

        work_id = "work-" + suffix
        authority.create_work_item(
            command("work_item.create", work_id, "work_item"),
            "local-scope",
            "local-slot",
            "a" * 40,
        )
        message_id = "message-" + suffix
        issued = command("message.send", message_id, "message")
        packet = DeliveryPacket(
            work_item_id=work_id,
            target_scope_id="local-scope",
            target_agent_slot_id="local-slot",
            accepted_revision=0,
            goal="Observe no-model original host scene",
            accepted_state_summary="revision zero",
            request=MODEL_PROMPT,
            source_baseline="a" * 40,
            expected_response="ACS_P1_CODEX_API_OK",
            activation="invoke",
            deadline=deadline - timedelta(seconds=1),
            maximum_attempts=1,
        )
        sent = service.send_message(
            issued,
            packet,
            endpoint_id=capacity.ready["endpoint_id"],
            binding_revision=capacity.ready["binding_revision"],
        )
        host_request = CodexHostRequest(
            action="dispatch",
            run_id=run_id,
            tenant_id=authority.tenant_id,
            message_id=message_id,
            command_id=issued.command_id,
            operation_id=sent.operation_id,
            endpoint_id=capacity.ready["endpoint_id"],
            source_commit="a" * 40,
            native_sha256=capacity.scene.host.policy.native_sha256,
            config_sha256=capacity.scene.host.policy.config_sha256,
        )
        if current_change is not None:
            with authority._connect() as database:
                if current_change == "grant_permissions":
                    database.execute(
                        "UPDATE grants SET permissions=%s WHERE grant_ref=%s",
                        (json.dumps(["message.read"]), authority.context.grant_ref),
                    )
                elif current_change == "scope_policy":
                    database.execute(
                        "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
                        (json.dumps({"revision": 2}),),
                    )
                else:
                    database.execute(
                        "UPDATE agent_slots SET status='revoked' "
                        "WHERE scope_id='local-scope' AND agent_slot_id='local-slot'"
                    )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(120)
            client.connect(str(capacity.server.socket_path))
            client.sendall(host_request.model_dump_json().encode() + b"\n")
            response = json.loads(client.recv(262144))
        if current_change is not None:
            assert response == {
                "schema_version": "acs-p1-codex-host-error/1", "state": "rejected",
            }
            assert capacity.driver.owned is None
            with authority._connect() as database:
                assert database.execute(
                    "SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (message_id,)
                ).fetchone() == (0,)
            proof = capacity.close()
            closed = True
            assert proof["status"] == "clean" and proof["boot_state"] is None
            assert proof["units_seen"] == [] and proof["remaining_pids"] == []
            return
        assert response["status"] == "delivered" and response["scene_readback"]
        lineage = response["scene_readback"]
        assert (
            lineage["run_id"],
            lineage["command_id"],
            lineage["message_id"],
            lineage["operation_id"],
        ) == (
            run_id,
            issued.command_id,
            message_id,
            sent.operation_id,
        )
        assert lineage["pg"]["attempt_count"] == 1
        assert lineage["pg"]["response_projection_count"] == 1
        assert lineage["driver"]["turn_start_dispatch_count"] == 1
        assert lineage["temporal"]["run_id"]
        assert lineage["os"]["remaining_pids"] == []
        raw = fixture_root / "lineage.json"
        raw.write_text(json.dumps(lineage, sort_keys=True), encoding="utf-8")
        raw.chmod(0o600)
        row = {
            "lineage_json": json.dumps(lineage, sort_keys=True),
            "pg_schema": capacity.schema,
            "raw_path": raw.name,
            "test_digest": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "host_request_json": host_request.model_copy(update={"action": "readback"}).model_dump_json(),
        }
        def pinned_host_read(request, identity, **options):
            assert options in ({}, {"socket_path": Path("/run/acs-p1/codex-host.sock")})
            result = capacity.scene.handle(request)
            assert result.status == "delivered"
            assert (result.run_id, result.command_id, result.message_id, result.operation_id) == (
                identity["run_id"], identity["command_id"],
                identity["message_id"], identity["operation_id"],
            )
            return result

        with monkeypatch.context() as local:
            local.setattr(lifecycle, "_host_result_from_socket", pinned_host_read)
            for kind in ("command_output", "postgresql", "sqlite", "temporal", "driver", "os"):
                assert read_codex_layer(
                    {
                        "postgres_dsn": os.environ["ACS_P1_DSN"],
                        "temporal_endpoint": "127.0.0.1:7239",
                        "temporal_namespace": "default",
                    },
                    fixture_root,
                    row,
                    kind,
                )
        proof = capacity.close()
        closed = True
        assert proof["status"] == "clean" and proof["boot_state"] == "stopped"
        assert proof["remaining_pids"] == []
        assert list((capacity.host_root / "systemd-env").iterdir()) == []
    finally:
        if capacity is not None:
            if not closed:
                capacity.close()
            with psycopg.connect(os.environ["ACS_P1_DSN"], autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(capacity.schema))
                )
            root = capacity.host_root.resolve(strict=True)
            assert root.parent == Path(f"/run/user/{os.geteuid()}/acs-p1-codex").resolve(
                strict=True
            )
            shutil.rmtree(root)
        assert fixture_root.resolve(strict=True).parent == source.resolve(strict=True)
        shutil.rmtree(fixture_root)

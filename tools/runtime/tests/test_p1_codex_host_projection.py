"""Synthetic Codex terminal projection through the restricted host Node path."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.codex_driver import AuthorizedOperation
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.models import CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
    CodexHostRunPolicy,
)
from runtime_tests.test_codex_driver import native as native  # noqa: PLC0414
from runtime_tests.test_codex_driver import operation
from runtime_tests.test_codex_driver import profile as profile  # noqa: PLC0414
from tools.runtime.p1_codex_host_scene import TemporalHostDispatcher
from tools.runtime.p1_codex_lifecycle import (
    CodexSceneRejected,
    project_original_terminal,
    read_codex_layer,
    read_codex_scene,
)


@pytest.mark.skipif(
    not (os.getenv("ACS_P1_DSN") and os.getenv("ACS_P1_TEMPORAL_ENDPOINT")),
    reason="actual PostgreSQL and Temporal are required",
)
def test_host_node_temporal_then_node_pg_terminal_projection_from_original_turn(native, tmp_path):
    base = os.environ["ACS_P1_DSN"]
    schema = "codex_host_scene_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema}")
    try:
        authority = DomainAuthority(dsn)
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
        native.driver.identity = replace(native.driver.identity, agent_slot_id="local-slot")
        node = NodeJournal(
            tmp_path / "node.sqlite",
            machine_id="fixture-machine",
            node_id=native.driver.identity.node_id,
            boot_incarnation=native.driver.identity.node_boot_id,
        )
        native.driver.spawn(operation("host-scene-spawn"))
        run_id = "p1-run-" + uuid.uuid4().hex
        suffix = run_id.removeprefix("p1-run-")[:24]
        commit = "a" * 40
        issued = datetime.now(UTC)
        deadline = issued + timedelta(seconds=90)

        def command(name, target, revision=0):
            identity = uuid.uuid4().hex
            return CommandEnvelope(
                command_id="p1-host-" + identity,
                idempotency_key="key-" + identity,
                correlation_id=run_id,
                command_type=name,
                tenant_id=authority.tenant_id,
                authority_id=authority.context.authority_id,
                authority_incarnation=authority.context.authority_incarnation,
                principal_ref=authority.context.principal_ref,
                grant_ref=authority.context.grant_ref,
                target_kind="work_item" if name == "work_item.create" else "message",
                target_id=target,
                expected_revision=revision,
                issued_at=issued,
                deadline=deadline,
            )

        work_id = "work-" + suffix
        endpoint_id = "endpoint-" + suffix
        message_id = "message-" + suffix
        authority.create_work_item(
            command("work_item.create", work_id), "local-scope", "local-slot", commit
        )

        def authorize(invocation, binding):
            assert binding == native.driver.identity
            return AuthorizedOperation(
                invocation.invocation_id,
                invocation.command_id,
                invocation.message_id,
                invocation.envelope.grant_ref,
                invocation.envelope.packet.deadline,
            )

        adapter = NativeDeliveryAdapter(native.driver, authorize_invocation=authorize)
        endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", adapter)
        service = DeliveryService(authority, {endpoint_id: endpoint})
        service.bind_endpoint(
            command("message.bind", endpoint_id),
            EndpointBindingRequest(
                scope_id="local-scope",
                agent_slot_id="local-slot",
                expires_at=deadline,
            ),
        )
        packet = DeliveryPacket(
            work_item_id=work_id,
            target_scope_id="local-scope",
            target_agent_slot_id="local-slot",
            accepted_revision=0,
            goal="Bound one synthetic Codex terminal result",
            accepted_state_summary="revision zero",
            request="Reply with exactly ACS_P1_CODEX_API_OK. Do not call tools.",
            source_baseline=commit,
            expected_response="ACS_P1_CODEX_API_OK",
            activation="invoke",
            deadline=deadline,
            maximum_attempts=1,
        )
        sent_command = command("message.send", message_id)
        sent = service.send_message(
            sent_command, packet, endpoint_id=endpoint_id, binding_revision=1
        )
        private = tmp_path / "host-private"
        private.mkdir(mode=0o700)
        executable = private / "codex"
        executable.write_bytes(b"synthetic-no-model-native\n")
        executable.chmod(0o500)
        config = private / "config.toml"
        config.write_bytes(b"synthetic-no-model-config\n")
        config.chmod(0o600)
        with authority._connect() as connection:
            scope_policy = connection.execute(
                "SELECT policy FROM scopes WHERE scope_id='local-scope'"
            ).fetchone()[0]
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
            source_commit=commit,
            native_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
            deadline=deadline,
        )
        temporal = TemporalHostDispatcher(
            DeliveryDispatcher(service),
            endpoint=os.environ["ACS_P1_TEMPORAL_ENDPOINT"],
            namespace=os.getenv("ACS_P1_TEMPORAL_NAMESPACE", "default"),
            task_queue="p1-host-" + suffix,
            deadline=deadline,
        )
        host = CodexHostNodeEndpoint(
            policy,
            temporal,
            private / "runs.sqlite",
            native_path=executable,
            config_path=config,
            fixture_mode=True,
        )
        host_request = CodexHostRequest(
            action="dispatch",
            run_id=run_id,
            tenant_id=authority.tenant_id,
            message_id=message_id,
            command_id=sent_command.command_id,
            operation_id=sent.operation_id,
            endpoint_id=endpoint_id,
            source_commit=commit,
            native_sha256=policy.native_sha256,
            config_sha256=policy.config_sha256,
        )
        response = host.handle(host_request)
        assert response.status == "delivered" and response.attempt_id
        assert temporal.last and temporal.last["provider_run_id"]
        assert native.state["turn_calls"] == 1
        dispatch = {
            "authority": authority,
            "service": service,
            "endpoint": endpoint,
            "adapter": adapter,
            "identity": {
                "tenant_id": authority.tenant_id,
                "message_id": message_id,
                "operation_id": sent.operation_id,
            },
            "attempt_id": response.attempt_id,
            "invocation_id": "delivery-invocation:" + response.attempt_id,
            "dispatch_id": response.dispatch_id,
            "workflow_id": temporal.last["workflow_id"],
            "provider_run_id": temporal.last["provider_run_id"],
        }
        native.state["turns"][0]["status"] = "completed"
        native.state["turns"][0]["items"].append(
            {
                "id": "fixture-answer",
                "type": "agentMessage",
                "text": "ACS_P1_CODEX_API_OK",
            }
        )
        projection = project_original_terminal(
            dispatch,
            node,
            native.driver,
            tmp_path / "artifacts",
            pause=lambda _seconds: None,
        )
        assert projection["disposition"] == "applied"
        assert native.state["turn_calls"] == 1
        assert (
            host.handle(host_request.model_copy(update={"action": "readback"})).status
            == "delivered"
        )
        readback = read_codex_scene(
            dispatch,
            node,
            native.driver,
            projection,
            tmp_path / "artifacts",
            source_commit=commit,
            source_tree="b" * 40,
            run_id=run_id,
            temporal_endpoint=os.environ["ACS_P1_TEMPORAL_ENDPOINT"],
            temporal_namespace=os.getenv("ACS_P1_TEMPORAL_NAMESPACE", "default"),
            os_proof={
                "unit": "acs-" + run_id + "-fixture.service",
                "termination_verified": True,
                "remaining_pids": [],
                "wrapper_exited": True,
                "environment_files_remaining": 0,
                "model_prompt_count": 1,
                "elapsed_seconds": 1,
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
        assert readback["pg"]["response_projection_count"] == 1
        assert readback["temporal"]["run_id"] == temporal.last["provider_run_id"]
        raw = tmp_path / "readback.json"
        raw.write_text(json.dumps(readback, sort_keys=True), encoding="utf-8")
        row = {
            "lineage_json": json.dumps(readback, sort_keys=True),
            "pg_schema": schema,
            "raw_path": raw.name,
            "test_digest": hashlib.sha256(raw.read_bytes()).hexdigest(),
        }
        loopback = {
            "postgres_dsn": base,
            "temporal_endpoint": os.environ["ACS_P1_TEMPORAL_ENDPOINT"],
            "temporal_namespace": os.getenv("ACS_P1_TEMPORAL_NAMESPACE", "default"),
        }
        for kind in ("command_output", "postgresql", "sqlite", "temporal", "driver"):
            assert read_codex_layer(loopback, tmp_path, row, kind)
        with pytest.raises(CodexSceneRejected, match="restricted host OS"):
            read_codex_layer(loopback, tmp_path, row, "os")
        with authority._connect() as connection:
            connection.execute(
                "UPDATE delivery_attempts SET status='interrupted' WHERE attempt_id=%s",
                (response.attempt_id,),
            )
        with pytest.raises(CodexSceneRejected, match="PostgreSQL"):
            read_codex_layer(loopback, tmp_path, row, "postgresql")
        with sqlite3.connect(tmp_path / "node.sqlite") as connection:
            connection.execute(
                "UPDATE mailbox SET command_id='changed' WHERE message_id=?", (message_id,)
            )
        with pytest.raises(CodexSceneRejected, match="SQLite"):
            read_codex_layer(loopback, tmp_path, row, "sqlite")
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

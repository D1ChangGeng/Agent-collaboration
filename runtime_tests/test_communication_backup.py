"""Actual PostgreSQL dump/restore in an explicitly owned disposable container.

This is a storage/recovery rehearsal with fixture Drivers, not model acceptance.
The restored authority stays quarantined; a fresh read-only generation reads
history, and neither old uncertain nor snapshot-pending commands are replayed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_archive import adopt_legacy_index
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_retirement import retire_tables
from runtime_tests.test_delivery import command

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def dataset(cursor):
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename")
    tables = [row[0] for row in cursor.fetchall()]
    result = {}
    for table in tables:
        cursor.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table)))
        rows = cursor.fetchall()
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True,
                            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()}
    return result


@pytest.mark.skipif(not os.getenv("ACS_POSTGRES_REHEARSAL_CONTAINER"), reason="owned PostgreSQL restore rehearsal is opt-in")
def test_snapshot_restore_preserves_history_and_fences_possible_post_snapshot_native_effects(comm, tmp_path):
    container = os.environ["ACS_POSTGRES_REHEARSAL_CONTAINER"]
    assert container == "acs-communication-test-20261031"
    base = conninfo_to_dict(comm.dsn)
    assert (base["host"], base["port"], base["dbname"]) == ("127.0.0.1", "55439", "acs_communication_test")
    prefix = (["wsl.exe", "-d", os.getenv("ACS_POSTGRES_REHEARSAL_WSL", "Ubuntu"), "--"] if os.name == "nt" else [])
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    def docker(*args, input=None):
        return subprocess.run([*prefix, "docker", *args], input=input, capture_output=True,
                              check=True, timeout=90, creationflags=flags).stdout
    labels = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", container))
    assert labels.get("acs.purpose") == "isolated-communication-tests"
    port = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", container))
    assert port["5432/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": "55439"}]

    # Seed a real stored legacy packet using the historical schema, explicitly
    # outside the normal public tool surface. Current message actions stay taskless.
    with comm.authority._connect() as connection:
        permissions = connection.execute("SELECT permissions FROM grants WHERE grant_ref=%s", (comm.authority.context.grant_ref,)).fetchone()[0]
        connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref=%s",
                           (json.dumps([*permissions, "work_item.create"]), comm.authority.context.grant_ref))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
            "VALUES (%s,'project-alpha','historical-route','local-scope','{}')", (comm.authority.tenant_id,))
    comm.authority.create_work_item(command(comm.authority, "work_item.create", "historical-work"),
                                   "local-scope", "slot-b", "historical-source")
    with comm.authority._connect() as connection:
        connection.execute("INSERT INTO collaboration_work_links VALUES (%s,'project-alpha','historical-work','historical-route','{}')",
                           (comm.authority.tenant_id,))
    packet = DeliveryPacket(work_item_id="historical-work", target_scope_id="local-scope", target_agent_slot_id="slot-b",
        accepted_revision=0, goal="Recorded historical goal", accepted_state_summary="Original summary",
        request="Original structured content is retained", source_baseline="historical-source", expected_response="Historical expectation")
    comm.dispatcher.service.send_message(command(comm.authority, "message.send", "historical-message"), packet,
                                         endpoint_id="endpoint-b", binding_revision=1)
    with comm.authority._connect() as connection:
        adopt_legacy_index(connection.cursor(), comm.authority.tenant_id)

    request = send(comm, content="Original request before backup", activation="message_only")["data"]
    reply = send(comm, "b", "a", "Original explicit reply", activation="message_only", reply_to=[request["message_handle"]])["data"]
    unknown = send(comm, content="Accepted Native with an unknown acknowledgement")["data"]
    pending = send(comm, content="This snapshot precedes the Native effect")["data"]
    accepted = comm.drivers["b"].invoke
    def lose_ack(invocation):
        result = accepted(invocation)
        if invocation.message_id == unknown["message_id"]:
            raise OSError("injected observation loss after fixture Native acceptance")
        return result
    comm.drivers["b"].invoke = lose_ack
    def identity(data):
        return {"tenant_id": comm.authority.tenant_id, "message_id": data["message_id"], "operation_id": data["operation_id"]}
    assert comm.dispatcher.dispatch(identity(unknown))["status"] == "uncertain"

    with comm.authority._connect() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        schema = connection.execute("SELECT current_schema()").fetchone()[0]
        assert re.fullmatch(r"comm_test_[0-9a-f]{32}", schema)
        before = dataset(connection.cursor())
        snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        backup = docker("exec", container, "pg_dump", "-U", "acs_test", "-d", "acs_communication_test",
                        "--schema", schema, "--format=custom", "--snapshot", snapshot)
    (tmp_path/"communication.dump").write_bytes(backup)
    # A rollback to the snapshot alone would forget this later effect.
    assert comm.dispatcher.dispatch(identity(pending))["status"] == "delivered"
    calls_before_restore = len(comm.drivers["b"].calls)
    assert calls_before_restore == 2

    target = "acs_restore_"+uuid.uuid4().hex
    assert target != base["dbname"] and re.fullmatch(r"acs_restore_[0-9a-f]{32}", target)
    admin_dsn = make_conninfo(comm.dsn, options="-ctimezone=UTC")
    restore_dsn = make_conninfo(comm.dsn, dbname=target)
    created = False
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
            created = True
        docker("exec", "-i", container, "pg_restore", "-U", "acs_test", "-d", target,
               "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error", input=backup)
        with psycopg.connect(restore_dsn) as connection:
            assert dataset(connection.cursor()) == before
            connection.execute("UPDATE authority_instances SET status='revoked'")
            # Snapshot-pending does not prove no Native effect occurred later.
            connection.execute("UPDATE delivery_messages SET state='uncertain',last_error='restored_snapshot_requires_reconciliation' "
                               "WHERE state IN ('queued','retry_wait','delivering')")
        # Fence the fixture source as well; the restored copy does not replace
        # an active original writer merely by changing its own database rows.
        with comm.authority._connect() as connection:
            connection.execute("UPDATE authority_instances SET status='revoked'")
        epoch = "read-recovery-"+uuid.uuid4().hex
        grant = "read-recovery-"+uuid.uuid4().hex
        read_permissions = ["profile.root_manager", "message.read", "project.read", "projects.read", "context.read",
                            "collaborators.read", "resources.read", "activity.read", "runtime.read"]
        with psycopg.connect(restore_dsn) as connection:
            connection.execute("INSERT INTO authority_instances(authority_id,authority_incarnation,status) VALUES (%s,%s,'active')",
                               (comm.authority.context.authority_id, epoch))
            connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                "scope_id,permissions,expires_at) SELECT %s,tenant_id,principal_ref,authority_id,%s,scope_id,%s,expires_at "
                "FROM grants WHERE grant_ref=%s", (grant, epoch, json.dumps(read_permissions), comm.authority.context.grant_ref))
            for table in ("collaboration_memberships", "collaboration_team_members"):
                connection.execute(sql.SQL("UPDATE {} SET grant_ref=%s WHERE tenant_id=%s AND grant_ref=%s").format(sql.Identifier(table)),
                                   (grant, comm.authority.tenant_id, comm.authority.context.grant_ref))
        retire_tables(SimpleNamespace(dsn=restore_dsn))
        ctx = replace(comm.authority.context, authority_incarnation=epoch, grant_ref=grant)
        authority = DomainAuthority(restore_dsn, context=ctx)
        authority._communication_maintenance_mode = "external"
        restored = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG,
                                             profile="root_manager"), comm.clients["a"].credential_provider)
        def read(reference):
            result = restored.call("read_message", {"project_id": "project-alpha", "handle": reference})["structuredContent"]
            assert result["ok"], result
            return result["data"]
        assert read(request["message_handle"])["content"] == "Original request before backup"
        assert read(request["message_handle"])["reply"]["message_id"] == reply["message_id"]
        assert read("message:project-alpha:historical-message")["content"] == packet.model_dump(mode="json")
        assert read(pending["message_handle"])["state"] == "uncertain"
        denied = restored.call("send_message", {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-b",
                                               "content": "Read-only recovery cannot send"})["structuredContent"]
        assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"
        dispatcher = DeliveryDispatcher(DeliveryService(authority, comm.dispatcher.service.endpoints))
        for data in (unknown, pending):
            assert dispatcher.dispatch(identity(data))["status"] == "uncertain"
        assert len(comm.drivers["b"].calls) == calls_before_restore
        facts = {"snapshot_rows_and_digests_preserved": True, "tables_verified": len(before),
            "backup_sha256": hashlib.sha256(backup).hexdigest(), "backup_bytes": len(backup),
            "source_and_restored_old_authorities_revoked": True, "read_only_new_generation": True,
            "original_packet_preserved": True, "explicit_reply_preserved": True,
            "post_snapshot_fixture_native_effects": 1, "native_replays_after_restore": 0,
            "model_requested": False, "source_schema": schema, "temporary_restore_database": target}
        evidence = ROOT/"integration_evidence/acs-retirement-20261031"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence/"backup-restore-facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    finally:
        if created:
            assert re.fullmatch(r"acs_restore_[0-9a-f]{32}", target) and target != "acs_communication_test"
            with psycopg.connect(admin_dsn, autocommit=True) as connection:
                owner = connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (target,)).fetchone()
                assert owner == (base["user"],)
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))

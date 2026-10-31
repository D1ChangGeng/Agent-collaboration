"""Production receiver identity checks with real storage, without requesting a model."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryService
from runtime.delivery_models import PACKET, EndpointBindingRequest
from runtime.delivery_node import InvocationPreCallRejected, LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.enrollment_models import NodeEnrollment, RuntimeRegistration
from runtime.errors import AuthorizationDenied
from runtime.mcp_runtime import McpRuntime
from runtime.models import CommandEnvelope
from runtime.node import NodeJournal
from runtime.project_service import ProjectService
from runtime.receiver_crypto import public_key
from runtime.receiver_models import EndpointRegistration
from runtime.surfaces import SharedService
from runtime_deployment.receiver_codex import CodexReceiverCapacity, validate_settings
from runtime_tests.test_communication import CATALOG, AcceptingDriver, call, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command as binding_command
from runtime_tests.test_receiver_domain_delivery import command as enrollment_command
from runtime_tests.test_receiver_domain_delivery import proof

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def receiver(f):
    capacity = object.__new__(CodexReceiverCapacity)
    capacity.authority = f.clients["b"].service.service.authority
    capacity.config = SimpleNamespace(access_mode="shared", clock_skew_seconds=0)
    return capacity


def test_shared_receiver_authorizes_committed_sender_separately_from_its_observer(comm):
    sent = send(comm)["data"]
    capacity = receiver(comm)
    assert capacity.authority.context.principal_ref != comm.authority.context.principal_ref
    with comm.authority._connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT command_json,packet_json FROM delivery_messages WHERE message_id=%s", (sent["message_id"],))
        raw_command, raw_packet = cursor.fetchone()
        command = CommandEnvelope.model_validate_json(json.dumps(raw_command), strict=True)
        packet = PACKET.validate_json(json.dumps(raw_packet), strict=True)
        capacity._authorize_domain_command(command, cursor, "runtime.invoke", packet.target_scope_id, packet)
        cursor.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (command.grant_ref,))
        with pytest.raises(AuthorizationDenied):
            capacity._authorize_domain_command(command, cursor, "runtime.invoke", packet.target_scope_id, packet)


def test_committed_unbound_client_origin_survives_recovery_to_a_registered_route(comm, tmp_path):
    token = "fixture-client-"+uuid.uuid4().hex
    ctx = replace(comm.authority.context, principal_ref="client:recovery", grant_ref="grant:client-recovery",
                  agent_slot_id=None, trusted_client=True, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    with comm.authority._connect() as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT %s,tenant_id,%s,authority_id,authority_incarnation,scope_id,permissions,expires_at FROM grants WHERE grant_ref=%s",
            (ctx.grant_ref, ctx.principal_ref, comm.authority.context.grant_ref))
        connection.execute("INSERT INTO scopes VALUES ('receiver-route-scope',%s,'{}','active')", (ctx.tenant_id,))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
            "VALUES (%s,'project-alpha','receiver-route','receiver-route-scope','{}')", (ctx.tenant_id,))
        connection.execute("INSERT INTO agent_slots VALUES ('route-receiver',%s,'receiver-route-scope','active')", (ctx.tenant_id,))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT 'grant:route-receiver',tenant_id,'agent:route-receiver',authority_id,authority_incarnation,'receiver-route-scope',permissions,expires_at "
            "FROM grants WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
        connection.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-alpha','agent:route-receiver','grant:route-receiver','engineer','route-receiver')",
                           (ctx.tenant_id,))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT 'grant:route-binding',tenant_id,principal_ref,authority_id,authority_incarnation,'receiver-route-scope',permissions,expires_at "
            "FROM grants WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
    driver = AcceptingDriver()
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path/"route.sqlite"), "receiver-route-scope", "route-receiver", driver)
    comm.authority._delivery_endpoints["endpoint-route"] = endpoint
    comm.dispatcher.service.endpoints["endpoint-route"] = endpoint
    binding_ctx = replace(comm.authority.context, grant_ref="grant:route-binding")
    binder = DomainAuthority(comm.dsn, context=binding_ctx)
    DeliveryService(binder, {"endpoint-route": endpoint}).bind_endpoint(binding_command(binder, "message.bind", "endpoint-route"),
        EndpointBindingRequest(scope_id="receiver-route-scope", agent_slot_id="route-receiver",
                               expires_at=comm.authority.canonical_now()+timedelta(minutes=5)))
    authority = DomainAuthority(comm.dsn, context=ctx)
    comm.clients["client"] = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)),
        CATALOG, profile="root_manager"), lambda: token)
    sent = call(comm, "client", "send_message", to="collaborator:project-alpha:route-receiver",
                content="Client-origin context must survive recovery")["data"]
    assert comm.dispatcher.dispatch({"tenant_id":ctx.tenant_id, "message_id":sent["message_id"],
                                    "operation_id":sent["operation_id"]})["status"] == "delivered"
    assert len(driver.calls) == 1
    capacity = receiver(comm)
    with comm.authority._connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE message_id=%s", (sent["message_id"],))
        row = cursor.fetchone()[0]
        envelope, _binding = comm.dispatcher._authorize(cursor, row)
        command = CommandEnvelope.model_validate_json(json.dumps(row["command_json"]), strict=True)
        capacity._authorize_domain_command(command, cursor, "runtime.invoke", envelope.packet.target_scope_id, envelope.packet)
        cursor.execute("DELETE FROM communication_clients WHERE address=%s", (sent["from"],))
        with pytest.raises(AuthorizationDenied):
            comm.dispatcher._authorize(cursor, row)


def test_receiver_refuses_legacy_native_activation_before_calling_bridge():
    calls = []
    class Bridge:
        def _invocation(self, _admission):
            return SimpleNamespace(envelope=SimpleNamespace(packet=SimpleNamespace(schema_version="acs-delivery/1")))
        def __call__(self, _admission):
            calls.append("native")
    capacity = object.__new__(CodexReceiverCapacity)
    capacity.bridge = Bridge()
    with pytest.raises(InvocationPreCallRejected, match="legacy_task_invocation_retired"):
        capacity.native_invoke(object())
    assert calls == []


def test_native_receiver_settings_do_not_require_execution_collector_storage(tmp_path):
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    if binary is None:
        pytest.skip("installed Codex version probe unavailable")
    settings = {"schema_version": "acs-receiver-codex-factory/1", "binding_id": "receiver-binding",
        "capacity_attempt_id": "receiver-capacity", "executable": binary, "cwd": str(tmp_path),
        "codex_home": str(tmp_path/"codex-home"), "driver_journal": str(tmp_path/"driver.sqlite"),
        "node_journal": str(tmp_path/"node.sqlite"), "runtime_id": "receiver-runtime"}
    observed = validate_settings(settings, execution_mode="native")
    assert "artifact_root" not in observed and "collector_max_reads" not in observed
    assert not hasattr(CodexReceiverCapacity, "_start_collector")
    assert not hasattr(CodexReceiverCapacity, "_projection_snapshot")


def enrolled_native_factory(f, tmp_path, monkeypatch, home):
    """Provision actual Node/Runtime records and enter the production factory."""
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    if binary is None:
        pytest.skip("installed Codex unavailable")
    with f.authority._connect() as connection:
        for grant, extra in ((f.authority.context.grant_ref, ["enrollment.manage"]),
                             (f.clients["b"].service.context.grant_ref, ["runtime.register"])):
            current = connection.execute("SELECT permissions FROM grants WHERE grant_ref=%s", (grant,)).fetchone()[0]
            connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref=%s", (json.dumps(list(set(current+extra))), grant))
    observer = f.clients["b"].service.service.authority
    key = SigningKey.generate()
    f.authority.enroll_node(enrollment_command(f.authority, "node.enroll", "node", "factory-node"),
        NodeEnrollment(scope_id="local-scope", agent_slot_id="slot-b", observer_grant_ref=observer.context.grant_ref,
            machine_id="factory-machine", boot_incarnation="factory-boot", public_key=public_key(key),
            expires_at=datetime.now(UTC)+timedelta(minutes=15)))
    request = RuntimeRegistration(node_id="factory-node", node_binding_revision=1, provider="receiver-tls",
        producer_grant_ref=observer.context.grant_ref, expires_at=datetime.now(UTC)+timedelta(minutes=14))
    command = enrollment_command(observer, "runtime.register", "runtime", "factory-runtime")
    observer.register_runtime(command, request, proof(observer, key, "factory-node", command,
                                                     {"request": request.model_dump(mode="json")}))
    policy = "c"*64
    registration = EndpointRegistration(registration_id="factory-registration", endpoint_id="factory-b", endpoint_revision=1,
        connection_ref="factory-local", tenant_id=f.authority.tenant_id, authority_id=f.authority.context.authority_id,
        authority_incarnation=f.authority.context.authority_incarnation, node_id="factory-node", node_binding_revision=1,
        runtime_id="factory-runtime", runtime_revision=1, machine_id="factory-machine", boot_incarnation="factory-boot",
        scope_id="local-scope", agent_slot_id="slot-b", tls_certificate_sha256="a"*64, config_sha256=policy)
    config = SimpleNamespace(access_mode="owner", binding=SimpleNamespace(registration=registration),
                             journal_generation=1, ledger_path=str(tmp_path/"receiver.sqlite"), clock_skew_seconds=0)
    settings = {"schema_version": "acs-receiver-codex-factory/1", "binding_id": "factory-binding-"+uuid.uuid4().hex,
        "capacity_attempt_id": "factory-capacity", "executable": binary, "cwd": str(tmp_path), "codex_home": str(home),
        "driver_journal": str(tmp_path/"factory-driver.sqlite"), "node_journal": str(tmp_path/"factory-node.sqlite"),
        "runtime_id": "factory-runtime"}
    monkeypatch.setenv("ACS_RECEIVER_DSN", f.dsn)
    return CodexReceiverCapacity(config, policy, settings)


@pytest.mark.skipif(os.getenv("ACS_REAL_NATIVE_TEST") != "1", reason="actual production factory session probe is opt-in")
def test_actual_factory_preparation_uses_live_node_identity_without_task_collector(comm, tmp_path, monkeypatch):
    home = tmp_path/"codex-home"
    home.mkdir()
    (home/"config.toml").write_text('approval_policy="never"\nsandbox_mode="read-only"\nproject_doc_max_bytes=0\n[features]\napps=false\nplugins=false\n', encoding="utf-8")
    capacity = enrolled_native_factory(comm, tmp_path, monkeypatch, home)
    try:
        assert capacity.authority.tenant_id == comm.authority.tenant_id
        assert capacity.authority.context.principal_ref == comm.clients["b"].service.context.principal_ref
        assert capacity.driver.thread_id and not hasattr(capacity, "collector")
        endpoint = LocalNodeEndpoint(capacity.node, "local-scope", "slot-b", capacity.adapter)
        comm.dispatcher.service.endpoints["factory-b"] = endpoint
        comm.authority._delivery_endpoints["factory-b"] = endpoint
        comm.dispatcher.service.bind_endpoint(binding_command(comm.authority, "message.bind", "factory-b"),
            EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b", expires_at=datetime.now(UTC)+timedelta(minutes=10)))
        configured = call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": "factory-b"}])
        native = configured["data"]["native_sessions"][0]
        assert native["state"] == "native_observed" and native["session_ref"] == capacity.driver.thread_id
        with capacity.journal._connect() as connection:
            calls = [json.loads(row[0])["method"] for row in connection.execute("SELECT body FROM driver_events WHERE kind='rpc_dispatch'")]
        assert calls.count("thread/start") == 1 and calls.count("turn/start") == 0
        facts = {"source": "production CodexReceiverCapacity", "version":capacity.driver.profile.version,
            "session_ref":capacity.driver.thread_id,"observer_principal":capacity.authority.context.principal_ref,
            "thread_starts":calls.count("thread/start"),"model_turns":calls.count("turn/start"),"collector_created":False}
        (ROOT/"integration_evidence/acs-retirement-20261031/actual-factory-session.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
    finally:
        capacity.close()

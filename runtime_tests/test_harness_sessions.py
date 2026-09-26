"""Real PostgreSQL checks for the versioned Harness session candidate."""
from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.delivery import DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidTransition,
    RevisionConflict,
    SchemaAdoptionError,
)
from runtime.harness_sessions import BindingChange, BindingResult, BindingRetire
from runtime.models import CommandEnvelope
from runtime.node import NodeJournal
from runtime.surfaces import PAYLOADS, SharedService, SurfaceCommand
from runtime_tests.test_delivery import FixtureDriver

BASE_18_SHA256 = "b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614"
BASE_19_SHA256 = "7eec78fd9d54b81d20724327e13f3a2237f95a9d5a2bc35f7799ebd3d30b5b9b"
PERMISSIONS = ("work_item.create", "harness_session.manage", "harness_session.read", "harness_session.result")


@pytest.fixture
def isolated_dsn():
    base = os.getenv("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is not configured; real PostgreSQL not measured")
    schema = "harness_binding_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(base, options=f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000")
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def command(authority, name, revision=0, *, key=None, target="work-harness", target_kind="work_item"):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return CommandEnvelope(
        command_id="cmd-" + identity, command_type=name, idempotency_key=key or "key-" + identity,
        correlation_id="harness-binding-test", tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref,
        target_kind=target_kind, target_id=target, expected_revision=revision,
        issued_at=now - timedelta(seconds=1), deadline=now + timedelta(minutes=5),
    )


def binding(binding_id, session, scope="local-scope"):
    return BindingChange(binding_id=binding_id, scope_id=scope, agent_slot_id="local-slot",
                         driver_kind="codex", native_session_ref=session, installed_version="0.153.2",
                         receipt_ref="artifact:binding-" + binding_id)


def prepare(authority):
    authority.initialize()
    authority.bootstrap_local_grant(PERMISSIONS)
    authority.create_work_item(command(authority, "work_item.create"), "local-scope", "local-slot", "baseline")


def query(authority, statement, params=()):
    with authority._connect() as connection:
        return connection.execute(statement, params).fetchall()


def test_binding_lifecycle_replay_scope_grant_and_late_result(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)
    sessions = authority.harness_sessions
    first = command(authority, "harness_session.attach")
    first_request = binding("bind-1", "native-1")
    assert sessions.change(first, first_request).revision == 1
    assert sessions.change(first, first_request).duplicate
    with pytest.raises(IdempotencyConflict):
        sessions.change(first, binding("bind-other", "native-other"))
    assert sessions.read(command(authority, "harness_session.read", 1))["active_binding_id"] == "bind-1"

    with pytest.raises(RevisionConflict):
        sessions.change(command(authority, "harness_session.replace", 0), binding("bind-2", "native-2"))
    with pytest.raises(AuthorizationDenied):
        sessions.change(command(authority, "harness_session.replace", 1), binding("bind-2", "native-2", "other-scope"))
    assert sessions.change(command(authority, "harness_session.replace", 1),
                           binding("bind-2", "native-2")).revision == 2

    late = sessions.admit_result(command(authority, "harness_session.result", 2),
                                  BindingResult(result_id="result-old", binding_id="bind-1",
                                                native_session_ref="native-1", result_ref="artifact:old"))
    assert late.state == "fenced_late"
    current = sessions.admit_result(command(authority, "harness_session.result", 2),
                                     BindingResult(result_id="result-new", binding_id="bind-2",
                                                   native_session_ref="native-2", result_ref="artifact:new"))
    assert current.state == "current"
    readback = sessions.read(command(authority, "harness_session.read", 2))
    assert (readback["scope_id"], readback["agent_slot_id"], readback["revision"]) == (
        "local-scope", "local-slot", 2)
    assert [(row["binding_id"], row["status"]) for row in readback["bindings"]] == [
        ("bind-1", "retired"), ("bind-2", "active")]
    assert readback["bindings"][0]["retired_command_id"]
    assert query(authority, "SELECT disposition FROM harness_session_result_admissions ORDER BY result_id") == [
        ("current",), ("fenced_late",)]
    assert query(authority, "SELECT count(*) FROM domain_events WHERE target_kind='harness_session'") == [(4,)]
    assert query(authority, "SELECT count(*) FROM outbox WHERE topic LIKE %s", ("harness_session.%",)) == [(4,)]

    with authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        sessions.change(command(authority, "harness_session.retire", 2), BindingRetire(binding_id="bind-2"))
    with pytest.raises(AuthorizationDenied):
        sessions.read(command(authority, "harness_session.read", 2))


def test_retire_then_attach_preserves_identity(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)
    sessions = authority.harness_sessions
    sessions.change(command(authority, "harness_session.attach"), binding("bind-1", "native-1"))
    assert sessions.change(command(authority, "harness_session.retire", 1),
                           BindingRetire(binding_id="bind-1")).state == "retired"
    assert sessions.read(command(authority, "harness_session.read", 2))["active_binding_id"] is None
    sessions.change(command(authority, "harness_session.attach", 2), binding("bind-2", "native-2"))
    assert sessions.read(command(authority, "harness_session.read", 3))["active_binding_id"] == "bind-2"
    with authority._connect() as connection:
        connection.execute("UPDATE work_items SET execution_status='cancelled' WHERE work_item_id='work-harness'")
    assert sessions.read(command(authority, "harness_session.read", 3))["bindings"][0]["status"] == "retired"
    assert sessions.admit_result(command(authority, "harness_session.result", 3),
                                 BindingResult(result_id="after-cancel", binding_id="bind-2",
                                               native_session_ref="native-2", result_ref="artifact:late")).state == "fenced_late"
    with pytest.raises(InvalidTransition):
        sessions.change(command(authority, "harness_session.replace", 3), binding("bind-3", "native-3"))
    assert sessions.change(command(authority, "harness_session.retire", 3),
                           BindingRetire(binding_id="bind-2")).state == "retired"


def test_revoked_slot_blocks_attach_without_ledger_or_head(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)
    with authority._connect() as connection:
        connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'")
    before = query(authority, "SELECT (SELECT count(*) FROM command_dedup),"
                              "(SELECT count(*) FROM domain_events),(SELECT count(*) FROM outbox)")
    with pytest.raises(AuthorizationDenied):
        authority.harness_sessions.change(command(authority, "harness_session.attach"),
                                          binding("revoked-bind", "revoked-native"))
    assert query(authority, "SELECT count(*) FROM harness_session_heads") == [(0,)]
    assert query(authority, "SELECT count(*) FROM harness_session_bindings") == [(0,)]
    assert query(authority, "SELECT (SELECT count(*) FROM command_dedup),"
                            "(SELECT count(*) FROM domain_events),(SELECT count(*) FROM outbox)") == before
    assert authority.harness_sessions.read(command(authority, "harness_session.read"))["bindings"] == []


def test_revoked_slot_fences_result_and_preserves_read_retire(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)
    sessions = authority.harness_sessions
    sessions.change(command(authority, "harness_session.attach"), binding("bind-1", "native-1"))
    with authority._connect() as connection:
        connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'")
    before = query(authority, "SELECT count(*) FROM domain_events WHERE target_kind='harness_session'")
    with pytest.raises(AuthorizationDenied):
        sessions.change(command(authority, "harness_session.replace", 1), binding("bind-2", "native-2"))
    assert query(authority, "SELECT count(*) FROM domain_events WHERE target_kind='harness_session'") == before
    late = sessions.admit_result(command(authority, "harness_session.result", 1),
                                  BindingResult(result_id="revoked-result", binding_id="bind-1",
                                                native_session_ref="native-1", result_ref="artifact:revoked"))
    assert late.state == "fenced_late"
    assert query(authority, "SELECT disposition FROM harness_session_result_admissions") == [("fenced_late",)]
    assert sessions.read(command(authority, "harness_session.read", 1))["active_binding_id"] == "bind-1"
    assert sessions.change(command(authority, "harness_session.retire", 1),
                           BindingRetire(binding_id="bind-1")).state == "retired"
    history = sessions.read(command(authority, "harness_session.read", 2))
    assert history["active_binding_id"] is None
    assert history["bindings"][0]["retired_command_id"]


def test_slot_revocation_race_serializes_before_attach(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)
    attach = command(authority, "harness_session.attach")
    grant_checked = Event()
    original_authorize = authority._authorize

    def signaled_authorize(*args, **kwargs):
        original_authorize(*args, **kwargs)
        grant_checked.set()

    authority._authorize = signaled_authorize
    with authority._connect() as revoker:
        revoker.execute("SELECT status FROM agent_slots WHERE agent_slot_id='local-slot' FOR UPDATE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(authority.harness_sessions.change, attach,
                                 binding("race-bind", "race-native"))
            assert grant_checked.wait(10)
            assert not future.done()
            revoker.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'")
            revoker.commit()
            with pytest.raises(AuthorizationDenied):
                future.result(timeout=10)
    assert query(authority, "SELECT count(*) FROM harness_session_heads") == [(0,)]
    assert query(authority, "SELECT count(*) FROM domain_events WHERE target_kind='harness_session'") == [(0,)]
    assert query(authority, "SELECT count(*) FROM outbox WHERE topic LIKE %s", ("harness_session.%",)) == [(0,)]


def test_attach_and_delivery_send_share_grant_then_work_lock_order(isolated_dsn, tmp_path):
    sender = DomainAuthority(isolated_dsn)
    prepare(sender)
    sender.bootstrap_local_grant(PERMISSIONS + ("delivery.manage", "message.send"))
    binder = DomainAuthority(isolated_dsn)
    node = NodeJournal(tmp_path / "cross-path-node.sqlite")
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", FixtureDriver())
    delivery = DeliveryService(sender, {"cross-endpoint": endpoint})
    delivery.bind_endpoint(
        command(sender, "message.bind", target="cross-endpoint", target_kind="message"),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="local-slot",
                               expires_at=datetime.now(UTC) + timedelta(minutes=5)),
    )
    sent = command(sender, "message.send", target="cross-message", target_kind="message")
    packet = DeliveryPacket(
        work_item_id="work-harness", target_scope_id="local-scope", target_agent_slot_id="local-slot",
        accepted_revision=0, goal="Cross-path lock ordering", accepted_state_summary="genesis",
        request="Queue one message", source_baseline="baseline", expected_response="receipt",
        activation="message_only", deadline=datetime.now(UTC) + timedelta(minutes=3),
    )
    attach = command(binder, "harness_session.attach")
    grant_locked, attach_ready = Event(), Event()
    original_sender_auth = sender._authorize
    original_binder_auth = binder._authorize
    first_send = True

    def sender_auth(*args, **kwargs):
        nonlocal first_send
        original_sender_auth(*args, **kwargs)
        if args[2] == "message.send" and first_send:
            first_send = False
            grant_locked.set()
            assert attach_ready.wait(10)

    def binder_auth(*args, **kwargs):
        attach_ready.set()
        assert grant_locked.wait(10)
        original_binder_auth(*args, **kwargs)

    sender._authorize = sender_auth
    binder._authorize = binder_auth
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent_future = pool.submit(delivery.send_message, sent, packet,
                                  endpoint_id="cross-endpoint", binding_revision=1)
        assert grant_locked.wait(10)
        attached_future = pool.submit(binder.harness_sessions.change, attach,
                                      binding("cross-bind", "cross-native"))
        sent_result = sent_future.result(timeout=15)
        attached_result = attached_future.result(timeout=15)
    assert sent_result.state == "message_queued" and attached_result.revision == 1
    assert query(sender, "SELECT state FROM delivery_messages WHERE message_id='cross-message'") == [
        ("queued",)]
    assert binder.harness_sessions.read(command(binder, "harness_session.read", 1))[
        "active_binding_id"] == "cross-bind"
    identities = (sent.command_id, attach.command_id)
    for table in ("command_dedup", "domain_events", "operations"):
        assert query(sender, f"SELECT count(*) FROM {table} WHERE command_id IN (%s,%s)",
                     identities) == [(2,)]
    assert query(sender, "SELECT count(*) FROM outbox o JOIN operations p "
                         "ON p.operation_id=o.operation_id WHERE p.command_id IN (%s,%s)",
                 identities) == [(2,)]
    before = query(sender, "SELECT (SELECT count(*) FROM command_dedup),"
                           "(SELECT count(*) FROM domain_events),(SELECT count(*) FROM outbox)")
    with pytest.raises(RevisionConflict):
        binder.harness_sessions.change(command(binder, "harness_session.attach"),
                                       binding("stale-bind", "stale-native"))
    assert query(sender, "SELECT (SELECT count(*) FROM command_dedup),"
                         "(SELECT count(*) FROM domain_events),(SELECT count(*) FROM outbox)") == before


def test_exact_1_9_to_1_10_migration_preserves_rows(isolated_dsn):
    fixture = Path(__file__).with_name("fixtures") / "schema-1.8-a942.sql"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == BASE_18_SHA256
    with psycopg.connect(isolated_dsn) as connection:
        connection.execute(fixture.read_bytes())
        connection.execute((Path(__file__).parents[1] / "runtime/schema_1_9.sql").read_bytes())
        connection.execute(
            "INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
            "VALUES ('acs-p1-runtime','1.9',%s)", (BASE_19_SHA256,),
        )
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) "
                           "VALUES ('migration-sentinel','local-tenant','{}','active')")
        connection.execute("INSERT INTO work_items(work_item_id,tenant_id,scope_id,agent_slot_id,state,"
                           "source_baseline,created_by) VALUES "
                           "('migration-work','local-tenant','migration-sentinel','historical-slot',"
                           "'candidate','source-baseline','historical-agent')")
        connection.execute("INSERT INTO command_dedup(tenant_id,idempotency_key,command_id,payload_hash,"
                           "hash_version,canonical_hash,migration_state,replay_policy,result_json) VALUES "
                           "('local-tenant','historical-key','historical-command',%s,'v2',%s,'current',"
                           "'replay_safe',%s)", ("a" * 64, "a" * 64,
                                               '{"command_id":"historical-command","state":"candidate"}'))
        before = connection.execute(
            "SELECT row_to_json(w)::text FROM work_items w WHERE work_item_id='migration-work'"
        ).fetchone()[0]
        journal_before = connection.execute(
            "SELECT row_to_json(d)::text FROM command_dedup d WHERE command_id='historical-command'"
        ).fetchone()[0]
    authority = DomainAuthority(isolated_dsn)
    authority.initialize()
    authority.initialize()
    schema_bytes = (Path(__file__).parents[1] / "runtime/schema.sql").read_text(encoding="utf-8").encode()
    assert query(authority, "SELECT schema_version,schema_checksum FROM runtime_schema_metadata") == [
        ("1.10", hashlib.sha256(schema_bytes).hexdigest())]
    assert query(authority, "SELECT status FROM scopes WHERE scope_id='migration-sentinel'") == [("active",)]
    assert query(authority, "SELECT row_to_json(w)::text FROM work_items w WHERE work_item_id='migration-work'") == [
        (before,)]
    assert query(authority, "SELECT row_to_json(d)::text FROM command_dedup d "
                            "WHERE command_id='historical-command'") == [(journal_before,)]
    assert query(authority, "SELECT count(*) FROM harness_session_bindings") == [(0,)]


def test_unknown_1_9_checksum_rejected_without_partial_schema(isolated_dsn):
    fixture = Path(__file__).with_name("fixtures") / "schema-1.8-a942.sql"
    with psycopg.connect(isolated_dsn) as connection:
        connection.execute(fixture.read_bytes())
        connection.execute((Path(__file__).parents[1] / "runtime/schema_1_9.sql").read_bytes())
        connection.execute(
            "INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
            "VALUES ('acs-p1-runtime','1.9',%s)", ("f" * 64,),
        )
    authority = DomainAuthority(isolated_dsn)
    with pytest.raises(SchemaAdoptionError):
        authority.initialize()
    assert query(authority, "SELECT schema_version,schema_checksum FROM runtime_schema_metadata") == [
        ("1.9", "f" * 64)]
    assert query(authority, "SELECT to_regclass('harness_session_heads')") == [(None,)]


def test_surface_contract_is_explicit():
    assert PAYLOADS["harness_session.attach"] is BindingChange
    assert PAYLOADS["harness_session.replace"] is BindingChange
    assert PAYLOADS["harness_session.retire"] is BindingRetire
    assert PAYLOADS["harness_session.result"] is BindingResult


def test_authenticated_surface_routes_binding_commands(isolated_dsn):
    authority = DomainAuthority(isolated_dsn)
    prepare(authority)

    class Authenticator:
        def authenticate(self, credential):
            assert credential == "test-credential"
            return authority.context

    service = SharedService(authority, Authenticator())
    attach = command(authority, "harness_session.attach")
    outer = SurfaceCommand(
        command_type=attach.command_type, target_id=attach.target_id,
        expected_revision=attach.expected_revision, command_id=attach.command_id,
        idempotency_key=attach.idempotency_key, correlation_id=attach.correlation_id,
        target_kind=attach.target_kind, issued_at=attach.issued_at,
        deadline=attach.deadline, payload=binding("surface-bind", "surface-native").model_dump(),
    )
    reply = service.handle(outer, "test-credential")
    assert reply.ok and reply.result["state"] == "active"
    read = command(authority, "harness_session.read", 1)
    read_reply = service.handle(SurfaceCommand(
        command_type=read.command_type, target_id=read.target_id,
        expected_revision=read.expected_revision, command_id=read.command_id,
        idempotency_key=read.idempotency_key, correlation_id=read.correlation_id,
        target_kind=read.target_kind, issued_at=read.issued_at,
        deadline=read.deadline, payload={},
    ), "test-credential")
    assert read_reply.ok and read_reply.result["active_binding_id"] == "surface-bind"

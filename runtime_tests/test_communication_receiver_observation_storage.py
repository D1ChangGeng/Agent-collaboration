"""Actual disposable PG receiver counters; Native observations are synthetic.

These tests exercise persisted metadata, transaction and source-event fences.
They do not qualify an installed Harness, live Session or Native input support.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from random import Random
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

import runtime.communication_event_storage as events
from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_event_storage import adopt_event_storage
from runtime.communication_receiver_observation_storage import (
    NAME,
    TABLE,
    ReceiverObservationCorrupt,
    adopt_receiver_observation_storage,
    read_receiver_observation,
    record_receiver_observation,
    verify_receiver_observation_storage,
)
from runtime.delivery import DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import SchemaAdoptionError
from runtime.node import NodeJournal
from runtime.project_common import digest
from runtime.project_service import ProjectService
from runtime.receiver_contract import ReceiverBinding
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, AcceptingDriver
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_receivers import measured
from runtime_tests.test_delivery import command

comm = comm_fixture
PROJECT = "project-alpha"
RECEIVER = "endpoint-b"


@pytest.fixture
def observed(comm, monkeypatch):
    with comm.authority._connect() as connection:
        adopt_receiver_observation_storage(connection)
    for endpoint in comm.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("observation storage contacted provider"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("observation storage inspected Native runtime"))
        monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("observation storage prepared Native runtime"))
    return comm


@pytest.fixture
def evented(observed):
    with observed.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_event_storage(connection)
    return observed


def record(f):
    with f.authority._connect() as connection:
        return connection.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE endpoint_id=%s", (RECEIVER,)).fetchone()[0]


def sample(f, source=None):
    source = source or record(f)
    context = f.authority.context
    return measured(ReceiverBinding(receiver_id=source["endpoint_id"], actor_address="collaborator:" + PROJECT + ":" + source["agent_slot_id"],
        binding_epoch=source["revision"], provider_generation=None, native_session_ref=None, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, execution_host_ref=source["machine_id"]))


def client(f):
    source = f.clients["a"]
    return CommunicationClientService(source.service, source.credential_provider())


def write(f, item=None, selected=None):
    selected = selected or record(f)
    item = item or sample(f, selected)
    return client(f)._transaction(PROJECT, "list_harnesses", lambda _bound, cursor, _root, _command:
        record_receiver_observation(cursor, f.authority.tenant_id, PROJECT, selected, item))


def read(f, selected=None, now=None):
    selected = selected or record(f)
    now = now or datetime.now(UTC)
    return client(f)._transaction(PROJECT, "list_harnesses", lambda _bound, cursor, _root, _command:
        read_receiver_observation(cursor, f.authority.tenant_id, PROJECT, selected, now))


def stored(f):
    with f.authority._connect() as connection:
        return connection.execute("SELECT to_jsonb(o) FROM " + TABLE + " o ORDER BY receiver_id").fetchall()


def intents(f):
    with f.authority._connect() as connection:
        return connection.execute("SELECT kind,resource_ref,resource_revision,audience_kind,scope_id,payload_json FROM communication_event_intents ORDER BY intent_id").fetchall()


def refresh(item, microseconds):
    delta = timedelta(microseconds=microseconds)
    return item.model_copy(update={"observations": tuple(observation.model_copy(update={
        "observed_at": observation.observed_at + delta if observation.observed_at else None,
        "expires_at": observation.expires_at + delta if observation.expires_at else None,
        "evidence_ref": "fixture:renewed-observation-" + str(microseconds)}) for observation in item.observations),
        "capabilities": tuple(capability.model_copy(update={"valid_until": capability.valid_until + delta if capability.valid_until else None,
            "evidence_ref": "fixture:renewed-capability-" + str(microseconds)}) for capability in item.capabilities)})


def test_missing_adoption_fails_without_ddl_or_source_repair(comm):
    with comm.authority._connect() as connection:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_receiver_observation_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone() == (None,)
    with pytest.raises(SchemaAdoptionError):
        write(comm)
    assert not any(driver.calls for driver in comm.drivers.values())


def test_explicit_adoption_is_idempotent_and_preserves_observation_counter(observed):
    first = write(observed)
    before = stored(observed)
    with observed.authority._connect() as connection:
        verify_receiver_observation_storage(connection)
        adopt_receiver_observation_storage(connection)
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() == ("1",)
    assert stored(observed) == before and read(observed).revision == first.revision == 1


def test_intrinsic_refresh_advances_revision_without_semantic_event_get_loops(evented):
    item = sample(evented).model_copy(update={"revision": 12345})
    first = write(evented, item)
    assert first.revision == 1 and first.binding_epoch == 1 and first.allowed_actions == ()
    assert write(evented, item).revision == 1
    initial = intents(evented)
    assert [row[0] for row in initial] == ["receiver.observed", "capability.changed"]
    current = item
    for number in range(1, 4):
        current = refresh(item, number)
        result = write(evented, current)
        assert result.revision == number + 1 and result.binding_epoch == 1
        assert intents(evented) == initial
    assert write(evented, current.model_copy(update={"allowed_actions": ("prepare_receiver", "resume_receiver")})).revision == 4
    assert intents(evented) == initial and read(evented).allowed_actions == ()


def test_collection_order_changes_full_dto_revision_without_semantic_invalidation(evented):
    item = sample(evented)
    item = item.model_copy(update={"capabilities": tuple(capability.model_copy(update={"conditions": ("fixture:first", "fixture:second")})
        if capability.name == "native.structured_input" else capability for capability in item.capabilities)})
    assert write(evented, item).revision == 1
    initial = intents(evented)
    reordered = item.model_copy(update={"observations": tuple(reversed(item.observations)),
        "capabilities": tuple(capability.model_copy(update={"conditions": tuple(reversed(capability.conditions))})
                              for capability in reversed(item.capabilities))})
    result = write(evented, reordered)
    assert result.revision == 2 and result.observations[0].axis == reordered.observations[0].axis
    assert result.capabilities[0].name == reordered.capabilities[0].name
    assert write(evented, reordered).revision == 2 and intents(evented) == initial


def test_input_capability_config_generation_and_epoch_changes_keep_one_monotonic_resource(evented):
    item = sample(evented)
    assert write(evented, item).revision == 1
    busy = item.model_copy(update={"observations": tuple(observation.model_copy(update={"value": "busy"})
        if observation.axis == "input" else observation for observation in item.observations)})
    assert write(evented, busy).revision == 2
    assert [row[0] for row in intents(evented) if row[2] == 2] == ["receiver.observed"]
    configured = busy.model_copy(update={"capability_scope": busy.capability_scope.model_copy(update={"config_digest": "c" * 64})})
    assert write(evented, configured).revision == 3
    assert [row[0] for row in intents(evented) if row[2] == 3] == ["receiver.observed", "capability.changed"]
    generated = configured.model_copy(update={"native_session_ref": "fixture:new-session",
        "capability_scope": configured.capability_scope.model_copy(update={"provider_generation": "fixture:new-generation"}),
        "observations": tuple(observation.model_copy(update={"provider_generation": "fixture:new-generation"}) for observation in configured.observations)})
    assert write(evented, generated).revision == 4
    with evented.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
    selected = record(evented)
    renewed = write(evented, sample(evented, selected), selected)
    assert renewed.binding_epoch == 2 and renewed.revision == 5
    assert len(stored(evented)) == 1
    assert all(row[1] == RECEIVER and row[3:5] == ("receiver", selected["scope_id"]) and row[5] == {} for row in intents(evented))


def test_unmeasured_and_expired_cached_evidence_is_unknown_without_provider_io(observed):
    absent = read(observed)
    assert absent.revision == 0 and absent.native_session_ref is None
    assert all(item.knowledge == "unknown" and item.value is None for item in absent.observations)
    write(observed)
    before = stored(observed)
    expired = read(observed, now=datetime.now(UTC) + timedelta(minutes=10))
    assert expired.revision == 1 and expired.native_session_ref is None
    assert all(item.knowledge == "unknown" and item.value is None for item in expired.observations)
    assert all(item.support == item.availability == "unknown" for item in expired.capabilities)
    assert stored(observed) == before and not any(driver.calls for driver in observed.drivers.values())


def test_cached_binding_or_node_selection_change_cannot_reuse_old_session(observed):
    previous = record(observed)
    write(observed)
    with observed.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1,node_id='fixture:replacement-node' WHERE endpoint_id=%s", (RECEIVER,))
    current = record(observed)
    for selected in (previous, current):
        result = read(observed, selected)
        assert result.revision == 1 and result.native_session_ref is None
        assert all(item.value is None for item in result.observations)
    assert write(observed, sample(observed, current), current).revision == 2
    assert read(observed, current).binding_epoch == 2


@pytest.mark.parametrize("damage", ["snapshot_digest", "selection_digest", "semantic_digest", "capability_digest", "counter", "address"])
def test_corrupt_persisted_data_is_unknown_on_read_and_refused_by_verify_or_write(observed, damage):
    item = sample(observed)
    write(observed, item)
    with observed.authority._connect() as connection:
        if damage in {"snapshot_digest", "selection_digest", "semantic_digest", "capability_digest"}:
            connection.execute(sql.SQL("UPDATE {} SET {}=%s").format(sql.Identifier(TABLE), sql.Identifier(damage)), ("0" * 64,))
        elif damage == "counter":
            connection.execute("UPDATE " + TABLE + " SET resource_revision=resource_revision+1,snapshot_json=jsonb_set(snapshot_json,'{revision}',to_jsonb(resource_revision+1))")
        else:
            connection.execute("UPDATE " + TABLE + " SET snapshot_json=jsonb_set(snapshot_json,'{address}','\"collaborator:private-project:hidden\"')")
    result = read(observed)
    assert result.native_session_ref is None and all(entry.value is None for entry in result.observations)
    assert "private-project" not in result.model_dump_json()
    for action in (verify_receiver_observation_storage, adopt_receiver_observation_storage):
        with observed.authority._connect() as connection, pytest.raises(SchemaAdoptionError):
            action(connection)
    with pytest.raises(ReceiverObservationCorrupt):
        write(observed, item)


@pytest.mark.parametrize("damage", ["column", "key", "foreign_key", "same_named_check", "generated_key", "hash_function"])
def test_schema_damage_is_refused_without_silent_adoption_repair(observed, damage):
    with observed.authority._connect() as connection:
        if damage == "column":
            connection.execute("ALTER TABLE " + TABLE + " DROP COLUMN observed_at")
        elif damage == "key":
            connection.execute("ALTER TABLE " + TABLE + " DROP CONSTRAINT communication_receiver_observations_pkey")
        elif damage == "foreign_key":
            name = connection.execute("SELECT conname FROM pg_constraint WHERE conrelid=to_regclass(%s) AND confrelid=to_regclass('delivery_endpoints')", (TABLE,)).fetchone()[0]
            connection.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(sql.Identifier(TABLE), sql.Identifier(name)))
        elif damage == "same_named_check":
            connection.execute("ALTER TABLE " + TABLE + " DROP CONSTRAINT receiver_observation_hashes")
            connection.execute("ALTER TABLE " + TABLE + " ADD CONSTRAINT receiver_observation_hashes CHECK(TRUE)")
        elif damage == "generated_key":
            connection.execute("ALTER TABLE " + TABLE + " ALTER COLUMN receiver_key DROP EXPRESSION")
        else:
            connection.execute("ALTER FUNCTION acs_receiver_observation_key(text) VOLATILE")
    for action in (verify_receiver_observation_storage, adopt_receiver_observation_storage):
        with observed.authority._connect() as connection, pytest.raises(SchemaAdoptionError):
            action(connection)


@pytest.mark.parametrize("mismatch", ["receiver", "address", "epoch", "host", "actual_node"])
def test_record_requires_same_actual_endpoint_and_typed_subject_before_writing(evented, mismatch):
    selected, item = record(evented), sample(evented)
    if mismatch == "receiver":
        item = item.model_copy(update={"receiver_id": "other-endpoint"})
    elif mismatch == "address":
        item = item.model_copy(update={"address": "collaborator:private-project:hidden"})
    elif mismatch == "epoch":
        item = item.model_copy(update={"binding_epoch": item.binding_epoch + 1})
    elif mismatch == "host":
        item = item.model_copy(update={"capability_scope": item.capability_scope.model_copy(update={"execution_host_ref": "other-host"})})
    else:
        selected["node_id"] = "stale-actual-node"
    with pytest.raises(ValueError):
        write(evented, item, selected)
    assert stored(evented) == [] and intents(evented) == []


def test_concurrent_metadata_refresh_serializes_counter_without_duplicate_semantic_events(evented):
    item = sample(evented)
    with ThreadPoolExecutor(max_workers=6) as pool:
        revisions = list(pool.map(lambda number: write(evented, refresh(item, number)).revision, range(6)))
    assert sorted(revisions) == list(range(1, 7))
    assert read(evented).revision == 6
    assert [row[0] for row in intents(evented)] == ["receiver.observed", "capability.changed"]


@pytest.mark.parametrize("held_fence", ["advisory", "row"])
def test_writer_rechecks_original_proof_expiry_after_serialized_counter_wait(observed, held_fence):
    f, selected = observed, record(observed)
    issued = f.authority.canonical_now()
    expires = issued + timedelta(seconds=2)
    item = sample(f, selected)
    item = item.model_copy(update={"observations": tuple(entry.model_copy(update={"observed_at": issued, "expires_at": expires})
        for entry in item.observations), "capabilities": tuple(entry.model_copy(update={"valid_until": expires})
        for entry in item.capabilities)})
    assert write(f, item, selected).native_session_ref is not None
    entered, worker = Event(), {}
    holder = f.authority._connect()
    pool = ThreadPoolExecutor(max_workers=1)
    future = None

    def waiting_writer():
        def selected_write(_bound, cursor, _root, _command):
            worker["pid"] = cursor.connection.info.backend_pid
            entered.set()
            return record_receiver_observation(cursor, f.authority.tenant_id, PROJECT, selected, item)
        return client(f)._transaction(PROJECT, "list_harnesses", selected_write)

    try:
        if held_fence == "advisory":
            holder.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s||':'||encode(acs_receiver_observation_key(%s),'hex'),0))",
                           (NAME + ":" + digest([f.authority.tenant_id, PROJECT]), RECEIVER))
        else:
            holder.execute("SELECT 1 FROM " + TABLE + " WHERE receiver_id=%s FOR UPDATE", (RECEIVER,))
        future = pool.submit(waiting_writer)
        assert entered.wait(5), "writer did not enter its actual authorized transaction"
        with f.authority._connect() as monitor:
            stop = monotonic() + 4
            while True:
                blocked, now = monitor.execute("SELECT %s=ANY(pg_blocking_pids(%s)),clock_timestamp()",
                                               (holder.info.backend_pid, worker["pid"])).fetchone()
                if blocked:
                    assert now < expires, "fixture proof expired before the actual lock wait"
                    break
                assert monotonic() < stop, "writer never blocked on the held PG fence"
                sleep(0.01)
            while monitor.execute("SELECT clock_timestamp()").fetchone()[0] <= expires:
                assert monotonic() < stop, "short proof expiry exceeded the bounded barrier"
                sleep(0.01)
    finally:
        # Release before joining even when a barrier assertion fails.
        holder.rollback()
        holder.close()
        pool.shutdown(wait=True)
    result = future.result(timeout=1)
    assert result.revision == 2 and result.native_session_ref is None
    assert all(entry.knowledge == "unknown" and entry.value is None for entry in result.observations)
    assert all(entry.support == entry.availability == "unknown" for entry in result.capabilities)
    assert all(entry.observed_at == issued and entry.expires_at == expires for entry in result.observations)
    with f.authority._connect() as connection:
        persisted, recorded_at = connection.execute("SELECT snapshot_json,observed_at FROM " + TABLE).fetchone()
    assert recorded_at >= expires and persisted["native_session_ref"] is None
    assert all(entry["knowledge"] == "unknown" and entry["value"] is None for entry in persisted["observations"])
    assert all(entry["support"] == entry["availability"] == "unknown" for entry in persisted["capabilities"])
    assert all(datetime.fromisoformat(entry["expires_at"]) == expires for entry in persisted["observations"])
    assert not any(driver.calls for driver in f.drivers.values())


def test_caller_rollback_retains_neither_observation_nor_event_intents(evented):
    selected, item = record(evented), sample(evented)
    with evented.authority._connect() as connection:
        assert record_receiver_observation(connection.cursor(), evented.authority.tenant_id, PROJECT, selected, item).revision == 1
        connection.rollback()
    assert stored(evented) == [] and intents(evented) == []


def test_event_producer_failure_rolls_back_helper_savepoint_and_preserves_callers_prior_work(evented, monkeypatch):
    selected, item = record(evented), sample(evented)
    original, attempts = events.record_event_intent, []

    def second_fails(*args, **kwargs):
        attempts.append(kwargs["kind"])
        if len(attempts) == 2:
            raise OSError("controlled event producer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(events, "record_event_intent", second_fails)
    with evented.authority._connect() as connection:
        connection.execute("UPDATE collaboration_projects SET name='Caller-owned earlier change' WHERE project_id=%s", (PROJECT,))
        with pytest.raises(OSError):
            record_receiver_observation(connection.cursor(), evented.authority.tenant_id, PROJECT, selected, item)
        assert connection.execute("SELECT name FROM collaboration_projects WHERE project_id=%s", (PROJECT,)).fetchone() == ("Caller-owned earlier change",)
    assert attempts == ["receiver.observed", "capability.changed"]
    assert stored(evented) == [] and intents(evented) == []


def test_unversioned_partial_event_store_never_silently_loses_observation_intent(observed):
    with observed.authority._connect() as connection:
        connection.execute("CREATE TABLE communication_event_intents(untrusted_partial INTEGER)")
    with pytest.raises(SchemaAdoptionError):
        write(observed)
    assert stored(observed) == []


def test_autocommit_cannot_split_observation_and_semantic_event_transaction(evented):
    with psycopg.connect(evented.dsn, autocommit=True) as connection, pytest.raises(ValueError):
        record_receiver_observation(connection.cursor(), evented.authority.tenant_id, PROJECT, record(evented), sample(evented))
    assert stored(evented) == [] and intents(evented) == []


def test_physical_key_collision_never_overwrites_or_reads_another_full_receiver_reference(observed):
    first = write(observed)
    before = stored(observed)
    with observed.authority._connect() as connection:
        connection.execute("CREATE OR REPLACE FUNCTION acs_receiver_observation_key(value TEXT) RETURNS BYTEA LANGUAGE SQL IMMUTABLE STRICT "
                           "AS $$ SELECT pg_catalog.sha256(pg_catalog.convert_to('endpoint-b','UTF8')); $$")
        other = connection.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE endpoint_id='endpoint-c'").fetchone()[0]
    with pytest.raises(ReceiverObservationCorrupt):
        write(observed, sample(observed, other), other)
    unknown = read(observed, other)
    assert unknown.receiver_id == "endpoint-c" and unknown.native_session_ref is None and unknown.revision == 0
    assert all(item.value is None for item in unknown.observations)
    assert stored(observed) == before and first.revision == 1
    with observed.authority._connect() as connection, pytest.raises(SchemaAdoptionError):
        verify_receiver_observation_storage(connection)


def test_legal_unicode_role_and_receiver_references_use_bounded_physical_key(comm, tmp_path):
    # This combination fits Core's existing tenant+endpoint key but adding a
    # 128-character project to the raw observation key would exceed 2704 bytes.
    points = Random(731).sample(range(0x10000, 0x110000), 656)
    tenant = "".join(chr(point) for point in points[:256])
    receiver = "".join(chr(point) for point in points[256:])
    project = "p" + "".join(Random(813).choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=127))
    assert (len(tenant), len(tenant.encode()), len(receiver), len(receiver.encode())) == (256, 1024, 400, 1600)
    schema = "obs_unicode_" + uuid4().hex
    with psycopg.connect(comm.dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    unicode_dsn = make_conninfo(comm.dsn, options="-c search_path=" + schema + " -c lock_timeout=5000 -c statement_timeout=10000")
    try:
        context = replace(comm.authority.context, tenant_id=tenant)
        authority = DomainAuthority(unicode_dsn, context=context)
        authority.initialize()
        permissions = {"project.adopt", "profile.root_manager", "delivery.manage", "message.read"}
        for definition in CATALOG["tools"].values():
            permissions.update(definition["security_scopes"])
        authority.bootstrap_local_grant(tuple(permissions))
        credential = comm.clients["a"].credential_provider()
        projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile="root_manager")
        projects.initialize()
        projects.admit_project(command(authority, "project.adopt", project, target_kind="project"),
            project_id=project, root_id="unicode-root", scope_id="local-scope", agent_slot_id="local-slot",
            name="Actual Unicode Role context", context_manifest={}, credential=credential)
        endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / "unicode-node.sqlite"), "local-scope", "local-slot", AcceptingDriver())
        DeliveryService(authority, {"unicode-source-endpoint": endpoint}).bind_endpoint(
            command(authority, "message.bind", "unicode-source-endpoint"), EndpointBindingRequest(scope_id="local-scope", agent_slot_id="local-slot",
                expires_at=authority.canonical_now() + timedelta(hours=1)))
        with authority._connect() as connection:
            # Trusted pre-existing source reference fixture: no API input limit
            # is bypassed or broadened, and Core's PK/FKs remain unchanged.
            connection.execute("UPDATE delivery_endpoints SET endpoint_id=%s WHERE endpoint_id='unicode-source-endpoint'", (receiver,))
            adopt_receiver_observation_storage(connection)
            selected = connection.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE endpoint_id=%s", (receiver,)).fetchone()[0]
        binding = ReceiverBinding(receiver_id=receiver, actor_address="collaborator:" + project + ":local-slot", binding_epoch=1,
            provider_generation=None, native_session_ref=None, authority_id=context.authority_id,
            authority_incarnation=context.authority_incarnation, execution_host_ref=selected["machine_id"])
        own = CommunicationClientService(projects, credential)
        saved = own._transaction(project, "list_harnesses", lambda _bound, cursor, _root, _command:
            record_receiver_observation(cursor, tenant, project, selected, measured(binding)))
        current = own._transaction(project, "list_harnesses", lambda _bound, cursor, _root, _command:
            read_receiver_observation(cursor, tenant, project, selected, datetime.now(UTC)))
        assert saved.receiver_id == current.receiver_id == receiver and saved.revision == current.revision == 1
        with authority._connect() as connection:
            verify_receiver_observation_storage(connection)
            key = connection.execute("SELECT octet_length(receiver_key),receiver_id FROM " + TABLE).fetchone()
            assert key == (32, receiver)
            # Prove the rejected layout's physical limit using only an optional
            # disposable test index; the production key remains the 32-byte hash.
            with pytest.raises(psycopg.errors.ProgramLimitExceeded), connection.transaction():
                connection.execute("CREATE INDEX unicode_raw_observation_key ON " + TABLE + "(tenant_id,project_id,receiver_id)")
    finally:
        with psycopg.connect(comm.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

"""Actual isolated PG receiver ACL/selection with explicitly synthetic readbacks.

Controlled callbacks establish projection and fencing behavior, not qualification
of an installed Harness, live Native Session, model input or lifecycle action.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic, sleep

import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_receivers import ReceiverQueryService
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_http import CommunicationHttpError
from runtime.communication_receiver_observation_storage import (
    TABLE as OBSERVATIONS,
)
from runtime.communication_receiver_observation_storage import (
    adopt_receiver_observation_storage,
    read_receiver_observation,
)
from runtime.delivery import DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.errors import AuthorizationDenied, NotFound
from runtime.node import NodeJournal
from runtime.receiver_contract import (
    AXES,
    CapabilityScope,
    Observation,
    ReceiverSnapshot,
    unknown_capabilities,
)
from runtime_tests.test_communication import AcceptingDriver, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command

comm = comm_fixture
PROJECT = "project-alpha"
CONTRACTS = ClientContracts()


class ReceiverClient(CommunicationClientService, ReceiverQueryService):
    """Exercise the mixin before/after the host service composes it."""


@pytest.fixture(autouse=True)
def adopted_client_storage(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
    for source in comm.clients.values():
        source.service.service.authority._receiver_evidence_enabled = True


def client(f, actor="a"):
    source = f.clients[actor]
    return ReceiverClient(source.service, source.credential_provider())


def measured(binding, *, expired=False, incomplete=False, future=False, missing_ttl=False, now=None, ttl_seconds=120):
    now = now or datetime.now(UTC)
    observed = now + timedelta(minutes=1) if future else now - timedelta(seconds=2)
    expiry = now - timedelta(seconds=1) if expired else observed + timedelta(seconds=ttl_seconds)
    capabilities = tuple(capability.model_copy(update={"support": "supported", "availability": "available",
        "evidence_ref": "fixture:synthetic-capability", "valid_until": expiry})
        if capability.name == "native.structured_input" else capability for capability in unknown_capabilities())
    values = {"connection": "connected", "process": "present", "session": "present", "input": "ready", "blocker": "none"}
    scope = CapabilityScope(adapter_id="fixture:synthetic-adapter", adapter_version="1", harness_kind="synthetic",
        harness_version=None if incomplete else "fixture-1", execution_host_ref=binding.execution_host_ref,
        binary_digest="a" * 64, config_digest="b" * 64, connection_epoch=binding.binding_epoch,
        provider_generation="fixture:synthetic-generation")
    observations = tuple(Observation(knowledge="observed", axis=axis, value=values[axis], source="native_api",
        observed_at=observed, expires_at=None if missing_ttl else expiry, binding_epoch=binding.binding_epoch,
        provider_generation=scope.provider_generation, evidence_ref="fixture:synthetic-readback", reason_code=None) for axis in AXES)
    return ReceiverSnapshot(receiver_id=binding.receiver_id, address=binding.actor_address,
        binding_epoch=binding.binding_epoch, revision=binding.binding_epoch, native_session_ref="fixture:synthetic-session",
        capability_scope=scope, capabilities=capabilities, observations=observations, allowed_actions=("prepare_receiver",))


def counts(f):
    with f.authority._connect() as connection:
        return [connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ("operations", "outbox", "delivery_messages", "communication_replies")]


def test_registered_active_endpoint_has_unknown_native_facts_without_lifecycle_or_legacy_ready_inference(comm, monkeypatch):
    for endpoint in comm.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("receiver read prepared runtime"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("legacy readiness was substituted for typed evidence"))
    before = counts(comm)
    page = client(comm).receivers(PROJECT)
    CONTRACTS.validate("ReceiverPage", page)
    assert {item["receiver_id"] for item in page["items"]} == {"endpoint-a", "endpoint-b", "endpoint-c"}
    for item in page["items"]:
        assert item["native_session_ref"] is None and item["allowed_actions"] == ["inspect"]
        assert item["binding_epoch"] == item["revision"] == 1
        assert item["capability_scope"]["provider_generation"] is None
        assert all(capability["support"] == capability["availability"] == "unknown" for capability in item["capabilities"])
        assert all(observation["knowledge"] == "unknown" and observation["value"] is None for observation in item["observations"])
    assert counts(comm) == before and not any(driver.calls for driver in comm.drivers.values())


def test_evidence_flag_off_preserves_bound_metadata_without_any_provider_read(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = False
    for endpoint in comm.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("disabled receiver evidence probed provider"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("disabled evidence probed legacy runtime"))
    service = client(comm)
    page = service.receivers(PROJECT)
    result = service.receiver(PROJECT, "endpoint-b")
    CONTRACTS.validate("ReceiverPage", page)
    assert result["receiver_id"] == "endpoint-b" and result["binding_epoch"] == 1
    assert result["native_session_ref"] is None and result["allowed_actions"] == ["inspect"]
    assert all(item["knowledge"] == "unknown" and item["value"] is None for item in result["observations"])


def test_fresh_typed_readback_is_bound_and_does_not_allow_provider_supplied_actions(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    monkeypatch.setattr(endpoint, "receiver_snapshot", measured)
    result = client(comm).receiver(PROJECT, "endpoint-b")
    CONTRACTS.validate("Receiver", result)
    assert result["receiver_id"] == "endpoint-b" and result["address"] == "collaborator:project-alpha:slot-b"
    assert result["native_session_ref"] == "fixture:synthetic-session"
    assert result["capability_scope"]["harness_kind"] == "synthetic" and result["allowed_actions"] == ["inspect"]
    assert next(capability for capability in result["capabilities"] if capability["name"] == "native.structured_input")["support"] == "supported"
    assert all(observation["knowledge"] == "observed" for observation in result["observations"])
    assert not any(driver.calls for driver in comm.drivers.values())


def test_known_unsupported_capability_is_preserved_without_inventing_support(comm, monkeypatch):
    def observe(binding):
        item = measured(binding)
        capabilities = tuple(capability.model_copy(update={"support": "unsupported", "availability": "unknown",
            "valid_until": datetime.now(UTC) + timedelta(minutes=1), "conditions": ("fixture:adapter-does-not-resume",)})
            if capability.name == "native.session_resume" else capability for capability in item.capabilities)
        return item.model_copy(update={"capabilities": capabilities})

    monkeypatch.setattr(comm.authority._delivery_endpoints["endpoint-b"], "receiver_snapshot", observe)
    result = client(comm).receiver(PROJECT, "endpoint-b")
    capability = next(item for item in result["capabilities"] if item["name"] == "native.session_resume")
    assert capability["support"] == "unsupported" and capability["availability"] == "unknown"
    assert result["allowed_actions"] == ["inspect"]


def test_t060_legacy_provider_missing_state_publishes_unknown_observation_without_inventing_idle(comm, monkeypatch):
    from runtime.communication_client_viewer_storage import adopt_viewer_storage
    from runtime.communication_event_storage import adopt_event_storage
    from runtime_tests.test_communication_client_events import anchor, publish

    f, own = comm, client(comm)
    with f.authority._connect() as connection:
        adopt_viewer_storage(connection)
        adopt_event_storage(connection)
        adopt_receiver_observation_storage(connection)
    f.authority._communication_receiver_observation_available = True
    provider = f.authority._delivery_endpoints["endpoint-b"]
    monkeypatch.setattr(provider, "receiver_snapshot", measured)
    initial = own.receiver(PROJECT, "endpoint-b")
    assert next(item for item in initial["observations"] if item["axis"] == "input")["value"] == "ready"
    publish(f)
    before = own.event_batch(PROJECT, after_cursor=anchor(own)).after_cursor
    # This actual old-provider callback lacks the new state/capability fields.
    monkeypatch.setattr(provider, "receiver_snapshot", lambda binding: {"receiver_id": binding.receiver_id})
    current = own.receiver(PROJECT, "endpoint-b")
    assert current["native_session_ref"] is None and current["allowed_actions"] == ["inspect"]
    assert all(item["knowledge"] == "unknown" and item["value"] is None for item in current["observations"])
    assert all(item["support"] == item["availability"] == "unknown" for item in current["capabilities"])
    publish(f)
    replay = own.event_batch(PROJECT, after_cursor=before)
    assert {item["kind"] for item in replay.events} == {"receiver.observed", "capability.changed"}
    assert all(item["resource_ref"] == "endpoint-b" and item["resource_revision"] == current["revision"] for item in replay.events)
    # Events are ref-only invalidations; the GET is the actual unknown DTO.
    assert all("idle" not in str(item["payload"]) and "content" not in item["payload"] for item in replay.events)
    assert own.receiver(PROJECT, "endpoint-b")["observations"] == current["observations"]
    assert not any(driver.calls for driver in f.drivers.values())


def test_page_rechecks_freshness_after_the_last_provider_observation(comm, monkeypatch):
    # Controlled clock/readbacks prove the final page boundary without sleeps.
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(comm.authority, "canonical_now", lambda cursor=None: clock[0])
    for endpoint in comm.authority._delivery_endpoints.values():
        def observe(binding):
            if binding.receiver_id == "endpoint-c":
                clock[0] += timedelta(seconds=3)
            return measured(binding, now=clock[0], ttl_seconds=4)
        monkeypatch.setattr(endpoint, "receiver_snapshot", observe)
    page = client(comm).receivers(PROJECT)
    earlier, last = page["items"][0], page["items"][-1]
    assert all(item["knowledge"] == "unknown" and item["value"] is None for item in earlier["observations"])
    assert all(item["knowledge"] == "observed" for item in last["observations"])


def test_live_page_rechecks_earlier_receiver_after_later_persistence_lock_wait(comm, monkeypatch):
    f = comm
    with f.authority._connect() as connection:
        adopt_receiver_observation_storage(connection)
    f.authority._communication_receiver_observation_available = True
    for endpoint in f.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", measured)
    service = client(f)
    assert service.receiver(PROJECT, "endpoint-b")["native_session_ref"] is not None
    holder = f.authority._connect()
    holder.execute("SELECT 1 FROM " + OBSERVATIONS + " WHERE receiver_id='endpoint-b' FOR UPDATE")
    issued = f.authority.canonical_now()
    expires = issued + timedelta(seconds=2)

    def early_proof(binding):
        item = measured(binding)
        return item.model_copy(update={"observations": tuple(entry.model_copy(update={"observed_at": issued, "expires_at": expires})
            for entry in item.observations), "capabilities": tuple(entry.model_copy(update={"valid_until": expires})
            for entry in item.capabilities)})

    monkeypatch.setattr(f.authority._delivery_endpoints["endpoint-a"], "receiver_snapshot", early_proof)
    persist = service._persist_receiver_observation
    entered, worker = Event(), {}

    def capture_wait(bound, cursor, project, record, snapshot):
        if record["endpoint_id"] == "endpoint-b":
            worker["pid"] = cursor.connection.info.backend_pid
            entered.set()
        return persist(bound, cursor, project, record, snapshot)

    monkeypatch.setattr(service, "_persist_receiver_observation", capture_wait)
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(service.receivers, PROJECT)
    try:
        assert entered.wait(5), "page never reached its later receiver persistence"
        with f.authority._connect() as monitor:
            stop = monotonic() + 4
            while True:
                blocked, now = monitor.execute("SELECT %s=ANY(pg_blocking_pids(%s)),clock_timestamp()",
                                               (holder.info.backend_pid, worker["pid"])).fetchone()
                if blocked:
                    assert now < expires, "earlier proof expired before the later actual PG wait"
                    break
                assert monotonic() < stop, "page did not block on the held later receiver row"
                sleep(0.01)
            while monitor.execute("SELECT clock_timestamp()").fetchone()[0] <= expires:
                assert monotonic() < stop
                sleep(0.01)
    finally:
        holder.rollback()
        holder.close()
        pool.shutdown(wait=True)
    page = future.result(timeout=1)
    first = page["items"][0]
    assert first["receiver_id"] == "endpoint-a" and first["native_session_ref"] is None
    assert first["allowed_actions"] == ["inspect"]
    assert all(entry["knowledge"] == "unknown" and entry["value"] is None for entry in first["observations"])
    assert all(entry["support"] == entry["availability"] == "unknown" for entry in first["capabilities"])
    assert all(datetime.fromisoformat(entry["expires_at"]) == expires for entry in first["observations"])
    assert page["items"][-1]["native_session_ref"] is not None
    with f.authority._connect() as connection:
        selected = connection.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE endpoint_id='endpoint-a'").fetchone()[0]
        current = read_receiver_observation(connection.cursor(), f.authority.tenant_id, PROJECT, selected, datetime.now(UTC))
    assert current.native_session_ref is None and all(entry.value is None for entry in current.observations)
    assert not any(driver.calls for driver in f.drivers.values())


@pytest.mark.parametrize("condition", ["expired", "incomplete", "future", "missing_ttl"])
def test_stale_or_unqualified_evidence_never_reports_observed_ready(comm, monkeypatch, condition):
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    monkeypatch.setattr(endpoint, "receiver_snapshot", lambda binding: measured(binding, **{condition: True}))
    result = client(comm).receiver(PROJECT, "endpoint-b")
    assert all(observation["knowledge"] == "unknown" and observation["value"] is None for observation in result["observations"])
    if condition in {"expired", "incomplete"}:
        assert all(capability["support"] == capability["availability"] == "unknown" for capability in result["capabilities"])
    if condition == "incomplete":
        assert result["native_session_ref"] is None


def test_receiver_io_occurs_after_db_locks_are_released_and_rebind_invalidates_result(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]

    def observe(binding):
        with comm.authority._connect() as connection:
            # A separate actual PG writer can acquire both identity and endpoint
            # fences while the controlled provider callback is running.
            connection.execute("SELECT grant_ref FROM grants WHERE grant_ref=%s FOR UPDATE NOWAIT", (comm.authority.context.grant_ref,))
            connection.execute("SELECT revision FROM delivery_endpoints WHERE endpoint_id='endpoint-b' FOR UPDATE NOWAIT")
            connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id='endpoint-b'")
        return measured(binding)

    monkeypatch.setattr(endpoint, "receiver_snapshot", observe)
    result = client(comm).receiver(PROJECT, "endpoint-b")
    assert result["binding_epoch"] == result["revision"] == 2 and result["native_session_ref"] is None
    assert all(observation["reason_code"] == "receiver_binding_changed" for observation in result["observations"])


def test_replacement_node_cannot_use_the_previous_provider_readback(comm, monkeypatch):
    probes = []
    monkeypatch.setattr(comm.authority._delivery_endpoints["endpoint-b"], "receiver_snapshot", lambda binding: probes.append(binding))
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET node_id='fixture:replacement-node' WHERE endpoint_id='endpoint-b'")
    result = client(comm).receiver(PROJECT, "endpoint-b")
    assert probes == [] and result["native_session_ref"] is None
    assert all(observation["value"] is None for observation in result["observations"])


def test_expired_shared_endpoint_is_no_longer_a_visible_receiving_binding(comm):
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET expires_at=clock_timestamp()-interval '1 second' WHERE endpoint_id='endpoint-b'")
    service = client(comm)
    assert {item["receiver_id"] for item in service.receivers(PROJECT)["items"]} == {"endpoint-a", "endpoint-c"}
    with pytest.raises(NotFound):
        service.receiver(PROJECT, "endpoint-b")


def test_provider_cannot_substitute_a_private_project_address(comm, monkeypatch):
    monkeypatch.setattr(comm.authority._delivery_endpoints["endpoint-b"], "receiver_snapshot",
        lambda binding: measured(binding).model_copy(update={"address": "collaborator:private-project:secret"}))
    result = client(comm).receiver(PROJECT, "endpoint-b")
    assert result["address"] == "collaborator:project-alpha:slot-b" and "private-project" not in str(result)
    assert result["native_session_ref"] is None


def test_provider_io_is_page_bounded_and_cursors_are_actor_and_binding_bound(comm, monkeypatch):
    probes = []
    for endpoint in comm.authority._delivery_endpoints.values():
        def observe(binding):
            probes.append(binding.receiver_id)
            return measured(binding)
        monkeypatch.setattr(endpoint, "receiver_snapshot", observe)
    service = client(comm)
    first = service.receivers(PROJECT, limit=1)
    assert probes == ["endpoint-a"] and first["items"][0]["receiver_id"] == "endpoint-a"
    second = service.receivers(PROJECT, limit=1, cursor=first["page"]["next_cursor"], snapshot_id=first["page"]["snapshot_id"])
    assert probes == ["endpoint-a", "endpoint-b"] and second["items"][0]["receiver_id"] == "endpoint-b"
    assert second["page"]["snapshot_id"] == first["page"]["snapshot_id"]
    assert all(len(token) <= 512 for page in (first, second) for token in page["page"].values() if token)
    for query in (lambda: client(comm, "c").receivers(PROJECT, cursor=first["page"]["next_cursor"]),
                  lambda: service.receivers(PROJECT, cursor="not-a-cursor"),
                  lambda: service.receivers(PROJECT, snapshot_id=first["page"]["next_cursor"]),
                  lambda: service.receivers(PROJECT, cursor=first["page"]["next_cursor"],
                                            snapshot_id=first["page"]["next_cursor"])):
        with pytest.raises(CommunicationHttpError) as error:
            query()
        assert error.value.code == "cursor_invalid"
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id='endpoint-b'")
    with pytest.raises(CommunicationHttpError) as error:
        service.receivers(PROJECT, cursor=first["page"]["next_cursor"])
    assert error.value.code == "cursor_invalid" and probes == ["endpoint-a", "endpoint-b"]


def test_long_endpoint_identity_does_not_expand_page_tokens_beyond_target_contract(comm):
    reference = "r" * 512
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET endpoint_id=%s WHERE endpoint_id='endpoint-b'", (reference,))
    service = client(comm)
    page = service.receivers(PROJECT, limit=1)
    CONTRACTS.validate("ReceiverPage", page)
    assert len(page["page"]["next_cursor"]) <= 512 and len(page["page"]["snapshot_id"]) <= 512
    assert service.receiver(PROJECT, reference)["receiver_id"] == reference


@pytest.mark.parametrize("when", ["before", "during"])
def test_live_grant_revocation_blocks_probing_or_returning_receiver_evidence(comm, monkeypatch, when):
    probes = []

    def revoke():
        with comm.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))

    def observe(binding):
        probes.append(binding)
        revoke()
        return measured(binding)

    monkeypatch.setattr(comm.authority._delivery_endpoints["endpoint-b"], "receiver_snapshot", observe)
    if when == "before":
        revoke()
    with pytest.raises(AuthorizationDenied):
        client(comm).receiver(PROJECT, "endpoint-b")
    assert len(probes) == (0 if when == "before" else 1)


def move_receiver_to_registered_route(f, name, scope, tmp_path):
    slot, endpoint_ref = "slot-" + name, "endpoint-" + name
    authority = f.clients[name].service.service.authority
    with authority._connect() as connection:
        connection.execute("INSERT INTO scopes VALUES (%s,%s,'{}','active')", (scope, authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) VALUES (%s,%s,%s,%s,'{}')",
                           (authority.tenant_id, PROJECT, scope, scope))
        connection.execute("UPDATE agent_slots SET scope_id=%s WHERE agent_slot_id=%s", (scope, slot))
        connection.execute("UPDATE grants SET scope_id=%s WHERE grant_ref=%s", (scope, authority.context.grant_ref))
    driver = AcceptingDriver()
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / (name + "-route.sqlite")), scope, slot, driver)
    f.authority._delivery_endpoints[endpoint_ref] = endpoint
    f.drivers[name] = driver
    DeliveryService(authority, f.authority._delivery_endpoints).bind_endpoint(command(authority, "message.bind", endpoint_ref, revision=1),
        EndpointBindingRequest(scope_id=scope, agent_slot_id=slot, expires_at=authority.canonical_now() + timedelta(hours=1)))


def test_route_engineer_reads_only_its_actual_scope_while_root_manager_sees_project_receivers(comm, tmp_path):
    move_receiver_to_registered_route(comm, "b", "fixture-route-b", tmp_path)
    move_receiver_to_registered_route(comm, "c", "fixture-route-c", tmp_path)
    manager = client(comm).receivers(PROJECT)
    ordinary = client(comm, "b").receivers(PROJECT)
    assert {item["receiver_id"] for item in manager["items"]} == {"endpoint-a", "endpoint-b", "endpoint-c"}
    assert [item["receiver_id"] for item in ordinary["items"]] == ["endpoint-b"]
    with pytest.raises(NotFound):
        client(comm, "b").receiver(PROJECT, "endpoint-c")
    assert not any(driver.calls for driver in comm.drivers.values())


def test_receiver_metadata_does_not_grant_access_to_private_message_operations(comm):
    original = send(comm, activation="message_only")["data"]
    outsider = client(comm, "c")
    receiver = outsider.receiver(PROJECT, "endpoint-b")
    assert receiver["receiver_id"] == "endpoint-b" and original["operation_id"] not in str(receiver)
    assert original["message_handle"] not in str(receiver)
    with pytest.raises(AuthorizationDenied):
        outsider.operation(original["operation_id"], project_id=PROJECT)

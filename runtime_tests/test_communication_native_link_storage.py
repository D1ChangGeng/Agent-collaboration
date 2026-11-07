"""Native linkage substrate: pure contracts plus disposable actual PostgreSQL.

Proof ports/readback are controlled fixtures. SQL owns only linkage metadata and
provenance; tests never contact a Host, launch Native, read transcripts or grant
Host permissions. Existing communication fixtures provide real Core/Scope rows.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic, sleep

import psycopg
import pytest
from pydantic import ValidationError

import runtime.communication_native_link_storage as storage
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_event_storage import adopt_event_storage
from runtime.communication_native_link_storage import (
    FILE,
    NAME,
    TABLES,
    NativeLink,
    NativeLinkCorrupt,
    NativeLinkIdentity,
    NativeLinkLimits,
    NativeLinkPosition,
    NativeLinkProofRejected,
    NativeLinkQuotaExceeded,
    NativeLinkWrite,
    adopt_native_link_storage,
    list_native_links,
    native_link_position,
    native_link_request,
    read_native_link,
    verify_native_link_storage,
    write_native_link,
)
from runtime.communication_storage import schema_definition
from runtime.errors import IdempotencyConflict, NotFound, RevisionConflict, SchemaAdoptionError
from runtime.native_provider_registry import NativeProviderRegistry
from runtime.native_view_models import NativeSelection, ProviderAdmission
from runtime.project_common import digest
from runtime.receiver_contract import (
    CapabilityScope,
    Observation,
    ReceiverBinding,
    ReceiverSnapshot,
    unknown_capabilities,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT, RECEIVER = "project-alpha", "endpoint-b"


def raw_body(**updates):
    return {"address": "collaborator:project:slot", "receiver_ref": "receiver", "expected_binding_epoch": 3,
        "provider_ref": "server-provider", "native_session_ref": "existing-session", "native_authority": "harness",
        "expected_revision": 0, "expected_host_ref": "actual-host", "expected_provider_generation": "actual-generation"} | updates


class TestNativeLinkContracts:
    @pytest.mark.parametrize("field", ["address", "receiver_ref", "expected_binding_epoch", "provider_ref", "native_session_ref",
        "native_authority", "expected_revision", "expected_host_ref", "expected_provider_generation"])
    def test_write_requires_exact_nine_fields(self, field):
        body = raw_body()
        body.pop(field)
        with pytest.raises(ValidationError):
            NativeLinkWrite.model_validate(body)

    @pytest.mark.parametrize("field", ["viewer_key", "principal_ref", "tenant_id", "scope_id", "url", "credential",
        "host_permission", "proof", "capabilities"])
    def test_write_cannot_supply_identity_proof_or_host_permissions(self, field):
        with pytest.raises(ValidationError):
            NativeLinkWrite.model_validate(raw_body(**{field: "untrusted"}))

    @pytest.mark.parametrize("updates", [{"expected_revision": True}, {"expected_binding_epoch": "3"},
        {"native_authority": "codex"}, {"expected_revision": -1}, {"expected_host_ref": ""}])
    def test_body_is_strict_and_native_authority_is_storage_wire_enum(self, updates):
        with pytest.raises(ValidationError):
            NativeLinkWrite.model_validate(raw_body(**updates))

    def test_unicode_references_are_bounded_by_characters(self):
        value = "😀" * 512
        assert NativeLinkWrite.model_validate(raw_body(provider_ref=value)).provider_ref == value
        with pytest.raises(ValidationError):
            NativeLinkWrite.model_validate(raw_body(provider_ref=value + "x"))

    def test_public_projection_requires_host_generation_and_only_qualified_capability_names(self):
        body = raw_body()
        public = {"link_id": "link", "project_id": "project", "address": body["address"], "receiver_ref": body["receiver_ref"],
            "binding_epoch": 3, "provider_ref": "provider", "native_session_ref": "session", "native_authority": "harness",
            "capabilities": ("native.structured_input",), "revision": 1, "host_ref": "host", "provider_generation": "generation"}
        assert NativeLink.model_validate(public).host_ref == "host"
        for field in ("host_ref", "provider_generation"):
            changed = dict(public)
            changed.pop(field)
            with pytest.raises(ValidationError):
                NativeLink.model_validate(changed)
        with pytest.raises(ValidationError):
            NativeLink.model_validate(public | {"capabilities": ("Host.read_all",)})

    def test_request_context_is_server_owned_and_access_mode_explicit(self):
        values = {"tenant_id": "tenant", "project_id": "project", "scope_id": "scope", "viewer_key": "viewer-" + "a" * 64,
            "authority_id": "authority", "authority_incarnation": "incarnation"}
        with pytest.raises(TypeError):
            NativeLinkIdentity(**values)
        with pytest.raises(ValueError):
            NativeLinkIdentity(**values, access_mode="guessed")
        identity = NativeLinkIdentity(**values, access_mode="shared")
        assert identity.resource("link") == ("tenant", "project", "scope", "link")
        assert storage._context(identity, "same-key") != storage._context(replace(identity, authority_incarnation="new-inc"), "same-key")
        assert storage._context(identity, "same-key") != storage._context(replace(identity, viewer_key="viewer-" + "b" * 64), "same-key")

    def test_pagination_position_binds_the_complete_unicode_identifier(self):
        value = "😀" * 512
        position = native_link_position(value)
        assert position.link_key == hashlib.sha256(value.encode()).digest()
        with pytest.raises(ValueError):
            NativeLinkPosition(position.link_key, "different")

    @pytest.mark.parametrize("field,value", [("links_per_scope", 0), ("history_per_link", True),
        ("requests_per_viewer", -1), ("metadata_bytes", 262145)])
    def test_quotas_are_positive_bounded_and_do_not_delete_history(self, field, value):
        with pytest.raises(ValueError):
            NativeLinkLimits(**(asdict(NativeLinkLimits()) | {field: value}))

    def test_schema_is_additive_hashed_and_retains_all_metadata(self):
        source, checksum, equivalents = schema_definition(FILE)
        text = source.decode()
        assert len(checksum) == 64 and ("1", checksum) in equivalents
        assert "UNIQUE(tenant_key,project_key,link_key)" in text
        assert "GENERATED ALWAYS AS (acs_native_link_key(link_id))" in text
        assert "ON DELETE CASCADE" not in text and "native_link_history_is_immutable" in text
        assert "transcript" not in storage.SHAPES[TABLES[0]]


@pytest.fixture
def links(comm, monkeypatch):
    with comm.authority._connect() as connection:
        adopt_native_link_storage(connection)
    for endpoint in comm.authority._delivery_endpoints.values():
        for method in ("prepare_runtime", "inspect_runtime", "receiver_snapshot"):
            monkeypatch.setattr(endpoint, method, lambda *_args: pytest.fail("link storage contacted Host"))
    return comm


@pytest.fixture
def evented(links):
    with links.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_event_storage(connection)
    return links


def owner(f, name="a", *, scope="local-scope", mode="shared"):
    source = f.clients[name]
    client = CommunicationClientService(source.service, source.credential_provider())

    def actual(bound, cursor, _root, _command):
        address = source.service._communication_address(cursor, PROJECT)
        return NativeLinkIdentity(bound.tenant_id, PROJECT, scope, client._viewer_actor_ref(PROJECT, address),
            bound.context.authority_id, bound.context.authority_incarnation, mode)

    return client._transaction(PROJECT, "read_message", actual)


def endpoint(f, receiver=RECEIVER):
    with f.authority._connect() as connection:
        return connection.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s",
                                  (f.authority.tenant_id, receiver)).fetchone()[0]


def proof(f, *, receiver=RECEIVER, session="controlled-existing-session", generation="controlled-current-generation",
          seconds=30, capability=True, source_changes=None):
    record = endpoint(f, receiver)
    context = f.authority.context
    binding = ReceiverBinding(receiver_id=receiver, actor_address=f"collaborator:{PROJECT}:{record['agent_slot_id']}",
        binding_epoch=record["revision"], provider_generation=None, native_session_ref=None,
        authority_id=context.authority_id, authority_incarnation=context.authority_incarnation,
        execution_host_ref=record["machine_id"])
    selection = NativeSelection(tenant_id=context.tenant_id, project_id=PROJECT, scope_id=record["scope_id"],
        agent_slot_id=record["agent_slot_id"], binding=binding, node_id=record["node_id"], boot_incarnation=record["boot_incarnation"])
    if source_changes:
        selection = selection.model_copy(update=source_changes)
    now = datetime.now(UTC)
    scope = CapabilityScope(adapter_id="controlled-admitted-port", adapter_version="1", harness_kind="controlled-readback",
        harness_version="fixture", execution_host_ref=selection.host_ref, binary_digest="a" * 64, config_digest="b" * 64,
        connection_epoch=binding.binding_epoch, provider_generation=generation)
    capabilities = tuple(c.model_copy(update={"support": "supported", "availability": "available", "evidence_ref": "controlled:capability",
        "valid_until": now + timedelta(seconds=seconds)}) if capability and c.name == "native.structured_input" else c
        for c in unknown_capabilities())
    observations = tuple(Observation(axis=axis, knowledge="observed", value=value, source="native_api", observed_at=now,
        expires_at=now + timedelta(seconds=seconds), binding_epoch=binding.binding_epoch, provider_generation=generation,
        evidence_ref="controlled:session-proof:" + axis, reason_code=None) for axis, value in (("connection", "connected"), ("session", "present")))
    snapshot = ReceiverSnapshot(receiver_id=receiver, address=binding.actor_address, binding_epoch=binding.binding_epoch,
        revision=binding.binding_epoch, native_session_ref=session, capability_scope=scope, capabilities=capabilities,
        observations=observations, allowed_actions=())

    class ControlledProofPort:
        def existing_session(self, selected):
            assert selected == selection
            return snapshot

    registry = NativeProviderRegistry(proof_ttl_seconds=30)
    registry.register(ProviderAdmission(provider_ref="actual-admitted-provider", native_authority="harness", selection=selection), ControlledProofPort())
    result = registry.prove("actual-admitted-provider", "harness", selection)
    assert result.state == "verified", result.reason_code
    return result


def body_for(value, *, revision=0, **changes):
    return {"address": value.selection.binding.actor_address, "receiver_ref": value.selection.binding.receiver_id,
        "expected_binding_epoch": value.selection.binding.binding_epoch, "provider_ref": value.provider_ref,
        "native_session_ref": value.native_session_ref, "native_authority": value.native_authority,
        "expected_revision": revision, "expected_host_ref": value.host_ref,
        "expected_provider_generation": value.provider_generation} | changes


def write(f, *, identity=None, value=None, body=None, key="request-one", link_id="link-one", limits=None):
    identity = identity or owner(f)
    value = value or proof(f)
    with f.authority._connect() as connection:
        return write_native_link(connection.cursor(), identity, link_id, body or body_for(value), value, key,
                                 **({"limits": limits} if limits else {}))


def read(f, link_id="link-one", *, identity=None, revision=None):
    with f.authority._connect() as connection:
        return read_native_link(connection.cursor(), identity or owner(f), link_id, revision=revision)


def rows(f, table=TABLES[0]):
    with f.authority._connect() as connection:
        return connection.execute("SELECT to_jsonb(t) FROM " + table + " t ORDER BY to_jsonb(t)::text").fetchall()


def events(f):
    with f.authority._connect() as connection:
        return connection.execute("SELECT kind,resource_ref,resource_revision,audience_kind,scope_id,payload_json FROM communication_event_intents ORDER BY intent_id").fetchall()


def test_missing_adoption_is_read_only_and_leaves_core_operations_available(comm):
    with comm.authority._connect() as connection:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_native_link_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert all(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None for table in TABLES)
    assert send(comm, activation="message_only")["ok"]


def test_actual_adoption_create_read_and_immutable_history(links):
    result = write(links)
    assert result == read(links) == read(links, revision=1)
    assert result["revision"] == 1 and result["capabilities"] == ["native.structured_input"]
    assert result["host_ref"] and result["provider_generation"] == "controlled-current-generation"
    before = [rows(links, table) for table in TABLES]
    with links.authority._connect() as connection:
        verify_native_link_storage(connection)
        adopt_native_link_storage(connection)
    assert [rows(links, table) for table in TABLES] == before
    assert not any(driver.calls for driver in links.drivers.values())


def test_explicit_rebind_changes_native_source_and_preserves_original_history(links):
    original = write(links)
    current = proof(links, session="controlled-rebound-session", generation="controlled-rebound-generation")
    updated = write(links, value=current, body=body_for(current, revision=1), key="explicit-rebind")
    assert updated["revision"] == 2 and updated["native_session_ref"] != original["native_session_ref"]
    assert read(links) == updated and read(links, revision=1) == original
    assert len(rows(links, TABLES[1])) == len(rows(links, TABLES[2])) == 2


def test_exact_retry_original_outcome_survives_rebind_epoch_change_and_expired_proof(links):
    identity, initial = owner(links), proof(links)
    body = body_for(initial)
    original = write(links, identity=identity, value=initial, body=body)
    renewed = proof(links, session="another-existing-session", generation="another-generation")
    write(links, identity=identity, value=renewed, body=body_for(renewed, revision=1), key="rebind")
    with links.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
        expired = initial.current(initial.expires_at)
        assert expired.state == "unknown"
        replay = write_native_link(connection.cursor(), identity, "link-one", body, expired, "request-one")
    assert replay == original and read(links)["revision"] == 2
    assert len(rows(links, TABLES[2])) == 2


def test_same_request_key_different_body_or_resource_conflicts(links):
    value, identity = proof(links), owner(links)
    write(links, value=value, identity=identity)
    for changed, link in ((body_for(value, expected_host_ref="forged-host"), "link-one"), (body_for(value), "another-link")):
        with pytest.raises(IdempotencyConflict):
            write(links, identity=identity, value=value, body=changed, link_id=link)
    assert len(rows(links)) == len(rows(links, TABLES[2])) == 1


def test_facade_receipt_lookup_miss_is_read_only_and_exact_hit_needs_no_new_host_proof(links):
    identity, value = owner(links), proof(links)
    body = body_for(value)
    with links.authority._connect() as connection:
        assert native_link_request(connection.cursor(), identity, "link-one", body, "request-one") is None
    assert all(rows(links, table) == [] for table in TABLES)
    original = write(links, identity=identity, value=value, body=body)
    with links.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
        assert native_link_request(connection.cursor(), identity, "link-one", body, "request-one") == original
    assert len(rows(links, TABLES[2])) == 1


def test_facade_receipt_lookup_checks_original_body_and_current_scope(links):
    identity, value = owner(links), proof(links)
    body = body_for(value)
    write(links, identity=identity, value=value)
    with links.authority._connect() as connection, pytest.raises(IdempotencyConflict):
        native_link_request(connection.cursor(), identity, "link-one", body | {"expected_revision": 1}, "request-one")
    with links.authority._connect() as connection:
        connection.execute("UPDATE scopes SET status='revoked' WHERE scope_id=%s", (identity.scope_id,))
    with links.authority._connect() as connection, pytest.raises(NotFound):
        native_link_request(connection.cursor(), identity, "link-one", body, "request-one")


def test_request_namespace_never_replays_for_another_actual_viewer(links):
    value = proof(links)
    write(links, identity=owner(links, "a"), value=value)
    with pytest.raises(RevisionConflict):
        write(links, identity=owner(links, "b"), value=value)
    assert len(rows(links, TABLES[2])) == 1


def test_original_receipt_still_requires_current_active_scope_context(links):
    value, identity = proof(links), owner(links)
    original_body = body_for(value)
    write(links, identity=identity, value=value, body=original_body)
    with links.authority._connect() as connection:
        connection.execute("UPDATE scopes SET status='revoked' WHERE scope_id=%s", (identity.scope_id,))
    with links.authority._connect() as connection, pytest.raises(NotFound):
        write_native_link(connection.cursor(), identity, "link-one", original_body, None, "request-one")


@pytest.mark.parametrize("changes", [{"native_session_ref": "forged-session"}, {"expected_host_ref": "forged-host"},
    {"expected_provider_generation": "forged-generation"}, {"provider_ref": "unregistered-provider"},
    {"native_authority": "orca"}, {"receiver_ref": "endpoint-c"}, {"expected_binding_epoch": 999}])
def test_request_strings_cannot_substitute_for_current_host_proof(links, changes):
    value = proof(links)
    with pytest.raises(NativeLinkProofRejected):
        write(links, value=value, body=body_for(value, **changes))
    assert all(rows(links, table) == [] for table in TABLES)


@pytest.mark.parametrize("changes", [{"tenant_id": "foreign-tenant"}, {"scope_id": "foreign-scope"},
    {"node_id": "different-node"}, {"boot_incarnation": "different-boot"}])
def test_typed_proof_selection_must_match_actual_core_source(links, changes):
    value = proof(links, source_changes=changes)
    with pytest.raises(NativeLinkProofRejected):
        write(links, value=value)
    assert rows(links) == []


def test_model_copy_corruption_and_raw_body_proof_are_rejected(links):
    identity, original = owner(links), proof(links)
    for corrupted in (original.model_copy(update={"native_session_ref": "tampered-copy"}), original.model_dump(mode="json")):
        with links.authority._connect() as connection, pytest.raises(NativeLinkProofRejected):
            write_native_link(connection.cursor(), identity, "link-one", body_for(original), corrupted, "request-one")
    assert rows(links) == []


def test_original_authority_incarnation_is_not_inferred_from_endpoint_strings(links):
    value = proof(links)
    wrong_binding = value.selection.binding.model_copy(update={"authority_incarnation": "wrong-incarnation"})
    selected = value.selection.model_copy(update={"binding": wrong_binding})
    source = value.source.model_copy(update={"selection": selected})
    forged = value.model_copy(update={"selection": selected, "source": source})
    with pytest.raises(NativeLinkProofRejected):
        write(links, value=forged)


def test_actual_endpoint_rebind_or_inactive_slot_invalidates_existing_source_proof(links):
    value = proof(links)
    with links.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
    with pytest.raises(NativeLinkProofRejected):
        write(links, value=value)
    value = proof(links)
    with links.authority._connect() as connection:
        connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='slot-b'")
    with pytest.raises(NativeLinkProofRejected):
        write(links, value=value)
    assert rows(links) == []


def test_new_write_requires_revision_zero_and_rebind_requires_current_revision(links):
    value = proof(links)
    with pytest.raises(RevisionConflict):
        write(links, value=value, body=body_for(value, revision=2))
    write(links, value=value)
    with pytest.raises(RevisionConflict):
        write(links, value=value, key="new-key-with-stale-revision")


def add_scope_receiver(f, scope="second-scope", slot="second-slot", receiver="second-endpoint"):
    source = endpoint(f)
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES (%s,%s,'active')", (scope, f.authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) VALUES (%s,%s,%s,%s,'{}')",
                           (f.authority.tenant_id, PROJECT, "trusted-fixture-route:" + digest(scope), scope))
        connection.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES (%s,%s,%s,'active')",
                           (slot, f.authority.tenant_id, scope))
        connection.execute("INSERT INTO delivery_endpoints SELECT tenant_id,%s,1,%s,%s,machine_id,node_id,boot_incarnation,"
            "supports_invoke,evidence_class,expires_at,'active',command_id,operation_id FROM delivery_endpoints WHERE endpoint_id=%s",
            (receiver, scope, slot, source["endpoint_id"]))
    return scope, receiver


def test_project_link_uri_cannot_be_created_twice_across_authorized_scopes(evented):
    first = write(evented)
    scope, receiver = add_scope_receiver(evented)
    different = owner(evented, scope=scope)
    value = proof(evented, receiver=receiver)
    with pytest.raises(NotFound):
        write(evented, identity=different, value=value, key="other-scope")
    with pytest.raises(NotFound):
        read(evented, identity=different)
    assert read(evented) == first and len(rows(evented)) == len(rows(evented, TABLES[1])) == 1
    assert events(evented) == [("native_link.changed", "link-one", 1, "receiver", "local-scope", {})]


def test_logical_address_cannot_be_changed_even_with_another_valid_source_proof(links):
    write(links)
    another = proof(links, receiver="endpoint-c")
    with pytest.raises(NativeLinkProofRejected, match="logical address"):
        write(links, value=another, body=body_for(another, revision=1), key="different-slot")
    assert read(links)["revision"] == 1


def test_receiver_rebind_to_another_current_endpoint_for_same_slot_is_explicit(links):
    first = write(links)
    with links.authority._connect() as connection:
        connection.execute("INSERT INTO delivery_endpoints SELECT tenant_id,'alternate-endpoint',1,scope_id,agent_slot_id,"
            "machine_id,node_id,boot_incarnation,supports_invoke,evidence_class,expires_at,status,command_id,operation_id "
            "FROM delivery_endpoints WHERE endpoint_id=%s", (RECEIVER,))
    another = proof(links, receiver="alternate-endpoint", session="alternate-session", generation="alternate-generation")
    second = write(links, value=another, body=body_for(another, revision=1), key="alternate-binding")
    assert second["receiver_ref"] == "alternate-endpoint" and second["revision"] == 2
    assert read(links, revision=1) == first


def test_native_link_event_is_atomic_minimal_and_exact_retry_emits_nothing(evented):
    value = proof(evented)
    result = write(evented, value=value)
    assert write(evented, value=value) == result
    assert events(evented) == [("native_link.changed", "link-one", 1, "receiver", "local-scope", {})]
    text = json.dumps(events(evented))
    assert value.native_session_ref not in text and value.provider_generation not in text


def test_parent_rollback_discards_link_history_receipt_and_source_event(evented):
    identity, value = owner(evented), proof(evented)
    with pytest.raises(RuntimeError, match="caller rollback"), evented.authority._connect() as connection:
        write_native_link(connection.cursor(), identity, "rolled-back", body_for(value), value, "rollback")
        raise RuntimeError("caller rollback")
    assert all(rows(evented, table) == [] for table in TABLES) and events(evented) == []
    assert send(evented, activation="message_only")["ok"]


def test_partial_or_unversioned_event_storage_fails_closed_but_absence_is_supported(links):
    with links.authority._connect() as connection:
        connection.execute("CREATE TABLE communication_event_intents(unversioned INTEGER)")
    with pytest.raises(SchemaAdoptionError):
        write(links)
    assert all(rows(links, table) == [] for table in TABLES)
    assert send(links, activation="message_only")["ok"]


def test_idle_autocommit_rejected_but_explicit_transaction_on_autocommit_is_supported(links):
    identity, value = owner(links), proof(links)
    with psycopg.connect(links.dsn, autocommit=True) as connection:
        with pytest.raises(ValueError, match="caller-owned"):
            write_native_link(connection.cursor(), identity, "link-one", body_for(value), value, "autocommit")
        with connection.transaction():
            result = write_native_link(connection.cursor(), identity, "link-one", body_for(value), value, "explicit")
    assert read(links) == result


@pytest.mark.parametrize("limits,second", [(NativeLinkLimits(links_per_scope=1), "new-resource"),
    (NativeLinkLimits(history_per_link=1), "rebind"), (NativeLinkLimits(requests_per_viewer=1), "new-resource")])
def test_configured_quotas_reject_new_metadata_without_losing_original_outcomes(links, limits, second):
    value = proof(links)
    original = write(links, value=value, limits=limits)
    with pytest.raises(NativeLinkQuotaExceeded):
        write(links, value=value, body=body_for(value, revision=1 if second == "rebind" else 0),
              link_id="link-one" if second == "rebind" else "another-link", key="second", limits=limits)
    assert write(links, value=value, limits=limits) == original
    assert len(rows(links)) == len(rows(links, TABLES[1])) == len(rows(links, TABLES[2])) == 1


def test_metadata_budget_rejects_before_any_accepted_history(links):
    with pytest.raises(NativeLinkQuotaExceeded, match="byte limit"):
        write(links, limits=NativeLinkLimits(metadata_bytes=256))
    assert all(rows(links, table) == [] for table in TABLES)


def test_concurrent_writers_use_actual_cas_and_keep_one_initial_version(links):
    value, identity = proof(links), owner(links)

    def attempt(key):
        try:
            return write(links, value=value, identity=identity, key=key)
        except RevisionConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("one", "two")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, RevisionConflict) for result in results) == 1
    assert len(rows(links, TABLES[1])) == 1


def test_concurrent_exact_key_writers_return_same_original_outcome(evented):
    value, identity = proof(evented), owner(evented)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write(evented, value=value, identity=identity), range(2)))
    assert results[0] == results[1] and len(rows(evented, TABLES[2])) == 1 and len(events(evented)) == 1


def test_scoped_pagination_is_metadata_only_and_exact_tuple_bound(links):
    identity, value = owner(links), proof(links)
    for identifier in ("link-b", "link-a", "link-c"):
        write(links, identity=identity, value=value, link_id=identifier, key="write:" + identifier)
    with links.authority._connect() as connection:
        first = list_native_links(connection.cursor(), identity, limit=2)
        second = list_native_links(connection.cursor(), identity, limit=2, after=native_link_position(first[-1]["link_id"]))
    assert len(first) == 2 and len(second) == 1
    assert len({item["link_id"] for item in first + second}) == 3
    assert len(rows(links, TABLES[2])) == 3


def test_wide_unicode_link_and_scope_use_small_hashed_physical_indexes(links):
    scope, receiver = add_scope_receiver(links, scope="😀" * 256)
    identity, value = owner(links, scope=scope), proof(links, receiver=receiver)
    result = write(links, identity=identity, value=value, link_id="😀" * 512, key="unicode")
    assert read(links, result["link_id"], identity=identity) == result
    with links.authority._connect() as connection:
        assert connection.execute("SELECT octet_length(scope_key),octet_length(link_key) FROM " + TABLES[0]).fetchone() == (32, 32)
        verify_native_link_storage(connection)


def barrier_write(f, *, lock="resource", endpoint_expiry=False, mode="shared"):
    identity = owner(f, mode=mode)
    if endpoint_expiry:
        with f.authority._connect() as connection:
            connection.execute("UPDATE delivery_endpoints SET expires_at=clock_timestamp()+interval '2 seconds' WHERE endpoint_id=%s", (RECEIVER,))
    value = proof(f, seconds=30 if endpoint_expiry else 2)
    pid_ready, pid = Event(), []
    holder = psycopg.connect(f.dsn)
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        if lock == "endpoint":
            holder.execute("SELECT 1 FROM delivery_endpoints WHERE endpoint_id=%s FOR UPDATE", (RECEIVER,))
        else:
            holder.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (NAME + ":resource:" + digest([identity.tenant_id, identity.project_id, "link-one"]),))

        def worker():
            with f.authority._connect() as connection:
                pid.append(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                pid_ready.set()
                return write_native_link(connection.cursor(), identity, "link-one", body_for(value), value, "barrier")

        future = executor.submit(worker)
        assert pid_ready.wait(2)
        limit, blocked = monotonic() + 2, False
        while monotonic() < limit:
            with f.authority._connect() as observer:
                blocked = observer.execute("SELECT wait_event_type='Lock' AND cardinality(pg_blocking_pids(pid))>0 FROM pg_stat_activity WHERE pid=%s", (pid[0],)).fetchone()[0]
            if blocked:
                break
            sleep(0.01)
        assert blocked, "writer did not reach the actual PostgreSQL lock barrier"
        expiry = endpoint(f)["expires_at"] if endpoint_expiry else value.expires_at
        expiry = datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry
        while datetime.now(UTC) <= expiry:
            sleep(0.01)
        holder.rollback()
        return future.result(timeout=3)
    finally:
        holder.rollback()
        holder.close()
        executor.shutdown(wait=True)


@pytest.mark.parametrize("lock", ["resource", "endpoint"])
def test_actual_lock_wait_cannot_commit_a_proof_that_expired_while_waiting(links, lock):
    with pytest.raises(NativeLinkProofRejected, match="expired"):
        barrier_write(links, lock=lock)
    assert all(rows(links, table) == [] for table in TABLES)


def test_shared_endpoint_lease_is_rechecked_after_serialization_wait(links):
    with pytest.raises(NativeLinkProofRejected, match="shared lease expired"):
        barrier_write(links, endpoint_expiry=True)
    assert rows(links) == []


def test_only_explicit_server_owner_context_can_ignore_technical_endpoint_lease(links):
    result = barrier_write(links, endpoint_expiry=True, mode="owner")
    assert result["revision"] == 1 and read(links, identity=owner(links, mode="owner")) == result


@pytest.mark.parametrize("table", TABLES)
def test_accepted_link_current_history_and_request_metadata_cannot_be_deleted(links, table):
    write(links)
    before = rows(links, table)
    with links.authority._connect() as connection, pytest.raises(psycopg.Error), connection.transaction():
        connection.execute("DELETE FROM " + table)
    assert rows(links, table) == before


@pytest.mark.parametrize("damage", ["check", "trigger", "function", "uri_unique"])
def test_adoption_verification_rejects_damaged_storage_without_repair(links, damage):
    write(links)
    with links.authority._connect() as connection:
        if damage == "check":
            connection.execute("ALTER TABLE communication_native_links DROP CONSTRAINT native_link_hashes")
        elif damage == "trigger":
            connection.execute("ALTER TABLE communication_native_link_history DISABLE TRIGGER acs_native_link_history_guard")
        elif damage == "function":
            connection.execute("CREATE OR REPLACE FUNCTION acs_native_link_key(value TEXT) RETURNS BYTEA LANGUAGE SQL IMMUTABLE STRICT AS $$ SELECT decode('00','hex'); $$")
        else:
            connection.execute("ALTER TABLE communication_native_links DROP CONSTRAINT communication_native_links_tenant_key_project_key_link_key_key")
        with pytest.raises(SchemaAdoptionError):
            verify_native_link_storage(connection)


def test_damaged_metadata_or_history_cannot_be_returned_as_a_valid_link(links):
    write(links)
    with links.authority._connect() as connection:
        connection.execute("ALTER TABLE communication_native_link_history DISABLE TRIGGER acs_native_link_history_guard")
        connection.execute("UPDATE communication_native_link_history SET proof_digest=%s", ("0" * 64,))
        connection.execute("ALTER TABLE communication_native_link_history ENABLE TRIGGER acs_native_link_history_guard")
    with pytest.raises(NativeLinkCorrupt):
        read(links)
    with links.authority._connect() as connection, pytest.raises(SchemaAdoptionError):
        verify_native_link_storage(connection)


def test_resource_hash_collision_is_checked_against_complete_ids_before_mutation(links):
    identity, value = owner(links), proof(links)
    original = write(links, identity=identity, value=value)
    with links.authority._connect() as connection:
        connection.execute("CREATE OR REPLACE FUNCTION acs_native_link_key(value TEXT) RETURNS BYTEA LANGUAGE SQL IMMUTABLE STRICT "
            "AS $$ SELECT pg_catalog.sha256(pg_catalog.convert_to(CASE WHEN value='collision-link' THEN 'link-one' ELSE value END,'UTF8')); $$")
    with pytest.raises(NativeLinkCorrupt, match="collision"):
        write(links, identity=identity, value=value, link_id="collision-link", key="collision")
    assert read(links) == original and len(rows(links)) == 1


def test_unversioned_or_partial_native_storage_is_never_automatically_adopted(comm):
    with comm.authority._connect() as connection:
        connection.execute("CREATE TABLE communication_native_links(unversioned INTEGER)")
        with pytest.raises(SchemaAdoptionError):
            adopt_native_link_storage(connection)
        assert connection.execute("SELECT count(*) FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone()[0] == 0

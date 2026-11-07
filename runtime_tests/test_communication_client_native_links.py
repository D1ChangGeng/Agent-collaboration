"""Actual Core ACL/storage plus existing LocalNode/Adapter source proof.

The configured Native profile is real and readback is deliberately controlled;
no executable, process, transport, transcript, model or Native input is used.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.client_contracts import ClientContracts, ClientContractViolation
from runtime.codex_driver import (
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.communication_client_native_links import ClientNativeLinkService
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_event_storage import adopt_event_storage
from runtime.communication_http import CommunicationHttpError
from runtime.communication_native_link_storage import (
    NativeLinkCorrupt,
    adopt_native_link_storage,
)
from runtime.delivery import DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    NotFound,
    RevisionConflict,
    SchemaAdoptionError,
)
from runtime.mcp_runtime import McpRuntime
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_provider_registry import LocalExistingSessionProvider, NativeProviderRegistry
from runtime.native_view_models import NativeSelection, ProviderAdmission
from runtime.project_common import digest
from runtime.project_service import ProjectService
from runtime.surface_config import CommunicationNativeLinkSettings
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command as domain_command
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT, RECEIVER, PROVIDER = "project-alpha", "endpoint-b", "configured-existing-provider"


def client(f, caller="b"):
    kind = CommunicationClientService if issubclass(CommunicationClientService, ClientNativeLinkService) else type(
        "UnMountedNativeLinkHarness", (ClientNativeLinkService, CommunicationClientService), {})
    source = f.clients[caller]
    return kind(source.service, source.credential_provider())


def raw_body(**updates):
    return {"address": "collaborator:project-alpha:slot-b", "receiver_ref": RECEIVER, "expected_binding_epoch": 1,
        "provider_ref": PROVIDER, "native_session_ref": "controlled-existing-session", "native_authority": "harness",
        "expected_revision": 0, "expected_host_ref": "actual-host", "expected_provider_generation": "actual-generation"} | updates


class InputOnly(ClientNativeLinkService):
    _validate = staticmethod(ClientContracts().validate)
    authority = SimpleNamespace(_communication_native_links_enabled=True,
                                _communication_native_link_settings=CommunicationNativeLinkSettings())

    def _transaction(self, *_args):
        raise AssertionError("invalid input reached SQL")


@pytest.mark.parametrize("field,value", [("principal_ref", "other"), ("scope_id", "other"), ("capabilities", []),
    ("provider_url", "https://untrusted.invalid"), ("expected_revision", True), ("native_authority", "codex")])
def test_public_write_cannot_supply_authority_or_untyped_binding_fields(field, value):
    with pytest.raises(ClientContractViolation):
        InputOnly().write_native_link(PROJECT, "link", raw_body(**{field: value}), "request")


@pytest.mark.parametrize("options", [{"limit": True}, {"limit": 101}, {"address": "x" * 513}, {"cursor": "x" * 513}])
def test_public_page_limits_and_references_are_bounded_before_sql(options):
    with pytest.raises(CommunicationHttpError):
        InputOnly().native_links(PROJECT, **options)


def test_feature_defaults_off_without_storage_or_host_access():
    facade = InputOnly()
    facade.authority = SimpleNamespace()
    for call in (lambda: facade.native_links(PROJECT), lambda: facade.write_native_link(PROJECT, "link", raw_body(), "key")):
        with pytest.raises(CommunicationHttpError, match="not enabled") as error:
            call()
        assert error.value.code == "capability_unsupported"


class Clock:
    def observation_time(self):
        return datetime.now(UTC)


@pytest.fixture
def native(comm, tmp_path, monkeypatch):
    f = comm
    with f.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_native_link_storage(connection)
    existing = f.authority._delivery_endpoints[RECEIVER]
    folder = tmp_path / "native-proof"
    folder.mkdir()
    executable, schema, home = folder / "controlled-profile", folder / "schema.json", folder / "home"
    executable.write_bytes(b"controlled Native profile; never executed")
    schema.write_text("{}", encoding="utf-8")
    home.mkdir()
    config = home / "config.toml"
    config.write_text('default_permissions="fixture"\napproval_policy="never"\n', encoding="utf-8")
    profile = LaunchProfile(str(executable), file_digest(executable), "0.153.2", str(schema), file_digest(schema),
        str(folder), str(home), file_digest(config), "fixture", {})
    clock = Clock()
    node = existing.journal
    identity = BindingIdentity(node.identity.node_id, node.identity.boot_incarnation,
        "controlled-existing-runtime", "configured-capacity", existing.agent_slot_id, 3)
    journal = DriverJournal(folder / "driver.sqlite", clock=clock)
    driver = CodexAppServerDriver("controlled-driver-binding", profile, journal, identity=identity,
        check_current=lambda *_args: None, clock=clock)
    driver.thread_id = "controlled-existing-session"
    reads = []

    def inspect():
        reads.append(True)
        return {"state": "idle", "session_ref": driver.thread_id, "observation": "native_driver_readback"}

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda *_args: pytest.fail("Native input authorization"),
        inspect_runtime=inspect, configure_runtime=lambda: pytest.fail("Native preparation"))
    endpoint = LocalNodeEndpoint(node, existing.scope_id, existing.agent_slot_id, adapter)
    f.authority._delivery_endpoints[RECEIVER] = endpoint
    registry = NativeProviderRegistry(clock=clock.observation_time)
    for source in f.clients.values():
        authority = source.service.service.authority
        authority._communication_native_links_enabled = True
        authority._communication_native_link_settings = CommunicationNativeLinkSettings()
        authority._native_provider_registry = registry
    facade = client(f)

    def selection(bound, cursor, root, _command):
        record = facade._receiver_records(bound, cursor, root, PROJECT, RECEIVER)[0]
        return NativeSelection(tenant_id=bound.tenant_id, project_id=PROJECT, scope_id=record["scope_id"],
            agent_slot_id=record["agent_slot_id"], binding=facade._receiver_binding(PROJECT, record),
            node_id=record["node_id"], boot_incarnation=record["boot_incarnation"])

    selected = facade._transaction(PROJECT, "list_harnesses", selection)
    provider = LocalExistingSessionProvider(endpoint)
    admission = ProviderAdmission(provider_ref=PROVIDER, native_authority="harness", selection=selected)
    registry.register(admission, provider)
    proof = registry.prove(PROVIDER, "harness", selected)
    assert proof.state == "verified", proof.reason_code
    body = raw_body(expected_binding_epoch=selected.binding.binding_epoch, expected_host_ref=proof.host_ref,
                    expected_provider_generation=proof.provider_generation, native_session_ref=proof.native_session_ref)
    reads.clear()
    for method in ("spawn", "resume", "invoke", "attach"):
        monkeypatch.setattr(driver, method, lambda *_args, **_kwargs: pytest.fail("Native effect called"))
    yield SimpleNamespace(f=f, facade=facade, registry=registry, admission=admission, provider=provider,
        endpoint=endpoint, driver=driver, journal=journal, reads=reads, body=body, config=config)
    driver.detach_transport()


def write(n, *, caller="b", link="link-one", key="key-one", **changes):
    return client(n.f, caller).write_native_link(PROJECT, link, n.body | changes, key)


def count(n, table="communication_native_links"):
    with n.f.authority._connect() as connection:
        return connection.execute("SELECT count(*) FROM " + table).fetchone()[0]


def deny_permission(n, caller, permission):
    context = n.f.clients[caller].service.context
    with n.f.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=(SELECT jsonb_agg(v) FROM jsonb_array_elements_text(permissions) v "
            "WHERE v<>%s) WHERE tenant_id=%s AND grant_ref=%s", (permission, context.tenant_id, context.grant_ref))


def test_actual_legacy_self_slot_proof_write_and_metadata_read_never_prepare_or_refresh(native, monkeypatch):
    n = native
    assert n.f.clients["b"].service.context.agent_slot_id is None  # Existing unique legacy binding still proves Slot B.
    created = write(n)
    assert created["revision"] == 1 and created["host_ref"] == n.body["expected_host_ref"]
    assert len(n.reads) == 1
    monkeypatch.setattr(n.provider, "existing_session", lambda *_args: pytest.fail("metadata GET contacted Host"))
    page = n.facade.native_links(PROJECT, address=n.body["address"])
    assert page["items"] == [created] and page["page"]["next_cursor"] is None
    assert count(n, "communication_messages") == count(n, "communication_replies") == 0
    assert not any(driver.calls for driver in n.f.drivers.values())


@pytest.mark.parametrize("permission", ["runtime.read", "runtime.invoke"])
def test_self_slot_write_keeps_actual_scoped_permissions(native, permission):
    deny_permission(native, "b", permission)
    with pytest.raises((AuthorizationDenied, PermissionError)):
        write(native)
    assert native.reads == [] and count(native) == 0


def test_ordinary_foreign_slot_cannot_gain_delegated_write_from_provider_or_body(native):
    with pytest.raises((AuthorizationDenied, PermissionError)):
        write(native, caller="c")
    assert native.reads == [] and count(native) == 0


@pytest.mark.parametrize("permission", ["collaborators.manage", "grants.manage", "delivery.manage"])
def test_delegated_manager_still_needs_each_existing_management_permission(native, permission):
    deny_permission(native, "a", permission)
    with pytest.raises((AuthorizationDenied, PermissionError)):
        write(native, caller="a")
    assert native.reads == [] and count(native) == 0


@pytest.mark.parametrize("changes", [{"provider_ref": "not-admitted"}, {"native_session_ref": "body-invented-session"},
    {"expected_provider_generation": "body-invented-generation"}, {"expected_host_ref": "body-invented-host"},
    {"native_authority": "orca"}, {"address": "collaborator:project-alpha:slot-c"}])
def test_binding_expectations_cannot_select_or_invent_a_native_source(native, changes):
    with pytest.raises((CommunicationHttpError, AuthorizationDenied)):
        write(native, **changes)
    assert count(native) == 0


def test_current_authorization_precedes_original_receipt_but_fresh_proof_and_epoch_do_not(native, monkeypatch):
    original = write(native)
    with native.f.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1,status='inactive' WHERE endpoint_id=%s", (RECEIVER,))
    monkeypatch.setattr(native.registry, "prove", lambda *_args: pytest.fail("exact receipt replay contacted Host"))
    assert write(native) == original
    with pytest.raises(IdempotencyConflict):
        write(native, native_session_ref="different-body")
    assert count(native, "communication_native_link_history") == 1
    deny_permission(native, "b", "runtime.invoke")
    with pytest.raises((AuthorizationDenied, PermissionError)):
        write(native)


@pytest.mark.parametrize("caller", ["a", "b"])
def test_original_scope_and_address_authorize_replay_after_real_endpoint_id_reassignment(native, monkeypatch, caller):
    original = write(native, caller=caller)
    reassigned_scope = "endpoint-reassignment-scope"
    with native.f.authority._connect() as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES (%s,%s,'active')",
                           (reassigned_scope, native.f.authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                           "VALUES (%s,%s,%s,%s,'{}')", (native.f.authority.tenant_id, PROJECT, reassigned_scope, reassigned_scope))
        connection.execute("UPDATE agent_slots SET scope_id=%s WHERE agent_slot_id='slot-c'", (reassigned_scope,))
    endpoints = native.f.authority._delivery_endpoints
    endpoints[RECEIVER] = LocalNodeEndpoint(native.endpoint.journal, reassigned_scope, "slot-c", native.f.drivers["c"])
    # A separate trusted Owner operator performs configuration; the tested
    # original Client keeps its existing shared-mode Grant and actual Slot.
    operator = copy(native.f.authority)
    operator.access_mode = "owner"
    delivery = DeliveryService(operator, endpoints)
    delivery.bind_endpoint(domain_command(operator, "message.bind", RECEIVER,
                                         revision=native.body["expected_binding_epoch"]),
        EndpointBindingRequest(scope_id=reassigned_scope, agent_slot_id="slot-c",
                               expires_at=native.f.authority.canonical_now() + timedelta(hours=1)))
    with native.f.authority._connect() as connection:
        assert connection.execute("SELECT agent_slot_id,scope_id,revision FROM delivery_endpoints WHERE endpoint_id=%s",
            (RECEIVER,)).fetchone() == ("slot-c", reassigned_scope, native.body["expected_binding_epoch"] + 1)
        assert connection.execute("SELECT scope_id,address FROM communication_native_links WHERE link_id='link-one'").fetchone() == (
            "local-scope", native.body["address"])
    reads = len(native.reads)
    monkeypatch.setattr(native.registry, "prove", lambda *_args: pytest.fail("original outcome replay contacted Host"))
    assert write(native, caller=caller) == original
    assert len(native.reads) == reads
    assert count(native, "communication_native_link_history") == count(native, "communication_native_link_requests") == 1
    with pytest.raises((AuthorizationDenied, NotFound, RevisionConflict)):
        write(native, caller=caller, key="fresh-after-reassignment")
    if caller == "a":
        with native.f.authority._connect() as connection:
            connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='slot-b'")
        with pytest.raises((AuthorizationDenied, NotFound)):
            write(native, caller=caller)


def test_missing_registry_rejects_new_write_but_retains_authorized_original_outcome(native):
    original = write(native)
    for source in native.f.clients.values():
        source.service.service.authority._native_provider_registry = None
    assert write(native) == original
    with pytest.raises(CommunicationHttpError) as error:
        write(native, link="new-link", key="new-key")
    assert error.value.code == "native_provider_not_registered"
    assert native.facade.native_links(PROJECT)["items"] == [original]


def test_trusted_client_delegation_has_no_slot_or_management_permission_shortcut(native, owner_client):
    native.f.clients["trusted"] = owner_client
    authority = owner_client.service.service.authority
    # The reused fixture is an Owner authority. This denial isolates the trusted
    # Client binding from Owner mode, whose existing policy intentionally does
    # not use operational Grant permissions as its authorization boundary.
    authority.access_mode = "shared"
    authority._communication_native_links_enabled = True
    authority._communication_native_link_settings = CommunicationNativeLinkSettings()
    authority._native_provider_registry = native.registry
    assert owner_client.service.context.trusted_client and owner_client.service.context.agent_slot_id is None
    deny_permission(native, "trusted", "delivery.manage")
    with pytest.raises((AuthorizationDenied, PermissionError)):
        write(native, caller="trusted")
    assert native.reads == [] and count(native) == 0


def test_owner_authority_keeps_its_existing_metadata_management_semantics(native, owner_client):
    native.f.clients["trusted"] = owner_client
    authority = owner_client.service.service.authority
    authority._communication_native_links_enabled = True
    authority._communication_native_link_settings = CommunicationNativeLinkSettings()
    authority._native_provider_registry = native.registry
    assert authority.access_mode == "owner"
    for permission in ("delivery.manage", "collaborators.manage", "grants.manage"):
        deny_permission(native, "trusted", permission)
    assert write(native, caller="trusted")["revision"] == 1
    assert len(native.reads) == 1


def test_same_principal_actual_slots_keep_separate_request_and_cursor_bindings(native):
    source = native.f.clients["b"]
    principal = native.f.clients["a"].service.context.principal_ref
    context = replace(source.service.context, principal_ref=principal, agent_slot_id="slot-b")
    with native.f.authority._connect() as connection:
        connection.execute("UPDATE grants SET principal_ref=%s WHERE grant_ref=%s", (principal, context.grant_ref))
        connection.execute("UPDATE collaboration_memberships SET principal_ref=%s WHERE grant_ref=%s",
                           (principal, context.grant_ref))
    authority = copy(source.service.service.authority)
    authority.context = context
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile="engineer")
    native.f.clients["b"] = McpRuntime(projects, source.credential_provider)
    first = write(native, caller="a", link="manager-view", key="same-raw-key")
    second = write(native, caller="b", link="slot-view", key="same-raw-key")
    assert first["link_id"] != second["link_id"]
    with native.f.authority._connect() as connection:
        assert connection.execute("SELECT count(DISTINCT viewer_key) FROM communication_native_link_requests").fetchone() == (2,)
    page = client(native.f, "a").native_links(PROJECT, limit=1)
    with pytest.raises(CommunicationHttpError):
        client(native.f, "b").native_links(PROJECT, cursor=page["page"]["next_cursor"], snapshot_id=page["page"]["snapshot_id"])


def test_root_grant_metadata_can_see_route_link_while_route_grant_cannot_see_another_scope(native):
    n = native
    with n.f.authority._connect() as connection:
        for suffix, caller, slot in (("native-route", "b", "slot-b"), ("unrelated-route", "c", "slot-c")):
            connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES (%s,%s,'active')",
                               (suffix, n.f.authority.tenant_id))
            connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                               "VALUES (%s,%s,%s,%s,'{}')", (n.f.authority.tenant_id, PROJECT, suffix, suffix))
            connection.execute("UPDATE agent_slots SET scope_id=%s WHERE agent_slot_id=%s", (suffix, slot))
            connection.execute("UPDATE grants SET scope_id=%s WHERE grant_ref=%s",
                               (suffix, n.f.clients[caller].service.context.grant_ref))
            connection.execute("UPDATE delivery_endpoints SET scope_id=%s,revision=revision+1 WHERE agent_slot_id=%s", (suffix, slot))
    n.endpoint.scope_id = "native-route"
    n.registry.unregister(PROVIDER, "harness")

    def actual(bound, cursor, root, _command):
        record = n.facade._receiver_records(bound, cursor, root, PROJECT, RECEIVER)[0]
        return NativeSelection(tenant_id=bound.tenant_id, project_id=PROJECT, scope_id=record["scope_id"],
            agent_slot_id=record["agent_slot_id"], binding=n.facade._receiver_binding(PROJECT, record),
            node_id=record["node_id"], boot_incarnation=record["boot_incarnation"])

    selected = n.facade._transaction(PROJECT, "list_harnesses", actual)
    n.registry.register(ProviderAdmission(provider_ref=PROVIDER, native_authority="harness", selection=selected), n.provider)
    created = write(n, expected_binding_epoch=selected.binding.binding_epoch)
    assert client(n.f, "a").native_links(PROJECT)["items"] == [created]
    assert client(n.f, "b").native_links(PROJECT)["items"] == [created]
    assert client(n.f, "c").native_links(PROJECT)["items"] == []


def test_expired_actual_proof_is_noneffect_and_quota_refusal_is_typed(native):
    native.registry.proof_ttl = timedelta(microseconds=1)
    with pytest.raises(CommunicationHttpError) as error:
        write(native)
    assert error.value.status_code == 409 and error.value.effect_state == "none" and count(native) == 0
    native.registry.proof_ttl = timedelta(seconds=5)
    authority = native.f.clients["b"].service.service.authority
    authority._communication_native_link_settings = CommunicationNativeLinkSettings(links_per_scope=1)
    write(native)
    with pytest.raises(CommunicationHttpError) as error:
        write(native, link="quota-excess", key="quota-excess")
    assert error.value.status_code == 429 and error.value.effect_state == "none"
    assert count(native) == count(native, "communication_native_link_requests") == 1


def test_stale_recorded_session_remains_metadata_until_explicit_cas(native):
    original = write(native)
    native.driver.thread_id = "replacement-existing-session"
    with native.f.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
    assert native.facade.native_links(PROJECT)["items"] == [original]
    assert len(native.reads) == 1
    with pytest.raises(RevisionConflict):
        write(native, key="fresh-key")


@pytest.mark.parametrize("mutation", ["rebind", "revoke", "feature_off", "profile_damage"])
def test_proof_io_holds_no_sql_lock_and_current_changes_prevent_commit(native, monkeypatch, mutation):
    original = native.provider.existing_session

    def interleave(selection):
        # NOWAIT proves the first admission transaction released its endpoint row lock.
        with native.f.authority._connect() as connection:
            connection.execute("SELECT 1 FROM delivery_endpoints WHERE endpoint_id=%s FOR UPDATE NOWAIT", (RECEIVER,))
            if mutation == "rebind":
                connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
            elif mutation == "revoke":
                context = native.f.clients["b"].service.context
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (context.grant_ref,))
        if mutation == "feature_off":
            native.f.clients["b"].service.service.authority._communication_native_links_enabled = False
        elif mutation == "profile_damage":
            native.config.write_text("changed after trusted admission", encoding="utf-8")
        return original(selection)

    monkeypatch.setattr(native.provider, "existing_session", interleave)
    with pytest.raises((CommunicationHttpError, AuthorizationDenied, RevisionConflict)):
        write(native)
    assert count(native) == count(native, "communication_native_link_history") == 0


def test_compact_pagination_checks_current_cut_filter_authorization_and_stale_cursor(native):
    for number in range(3):
        write(native, link="😀" * 505 + str(number), key="page-" + str(number))
    first = native.facade.native_links(PROJECT, limit=1)
    cursor, snapshot = first["page"]["next_cursor"], first["page"]["snapshot_id"]
    assert len(cursor) <= 512 and len(snapshot) <= 512
    second = native.facade.native_links(PROJECT, limit=1, cursor=cursor, snapshot_id=snapshot)
    assert second["items"][0]["link_id"] != first["items"][0]["link_id"]
    assert second["page"]["snapshot_id"] == snapshot
    with pytest.raises(CommunicationHttpError):
        native.facade.native_links(PROJECT, snapshot_id=cursor)
    for options in ({"address": native.body["address"]}, {"cursor": cursor[:-3] + "bad"}):
        selected = {"cursor": cursor, "snapshot_id": snapshot} | options
        with pytest.raises(CommunicationHttpError):
            native.facade.native_links(PROJECT, **selected)
    write(native, link="new-source", key="new-source")
    with pytest.raises(CommunicationHttpError):
        native.facade.native_links(PROJECT, cursor=cursor, snapshot_id=snapshot)
    deny_permission(native, "b", "runtime.read")
    with pytest.raises((AuthorizationDenied, PermissionError)):
        native.facade.native_links(PROJECT)


def test_event_visibility_is_current_metadata_acl_and_never_a_receiver_id_or_host_permission(native, monkeypatch):
    with native.f.authority._connect() as connection:
        adopt_event_storage(connection)
    written = write(native)
    with native.f.authority._connect() as connection:
        event = connection.execute("SELECT kind,resource_ref,scope_id,payload_json FROM communication_event_intents "
            "WHERE kind='native_link.changed'").fetchone()
    assert event == ("native_link.changed", written["link_id"], "local-scope", {})
    monkeypatch.setattr(native.provider, "existing_session", lambda *_args: pytest.fail("event visibility contacted Host"))

    def visible(bound, cur, root, command, **updates):
        return native.facade._native_link_event_visible(bound, cur, root, PROJECT, command,
            updates.get("link_id", written["link_id"]), updates.get("scope", "local-scope"))

    assert native.facade._transaction(PROJECT, "list_harnesses", visible)
    assert not native.facade._transaction(PROJECT, "list_harnesses", lambda *args: visible(*args, scope="foreign-scope"))
    assert not native.facade._transaction(PROJECT, "list_harnesses", lambda *args: visible(*args, link_id=RECEIVER))
    with native.f.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET status='inactive' WHERE endpoint_id=%s", (RECEIVER,))
    assert native.facade._transaction(PROJECT, "list_harnesses", visible)
    with native.f.authority._connect() as connection:
        connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='slot-b'")
    with pytest.raises((AuthorizationDenied, NotFound)):
        native.facade.native_links(PROJECT)


def test_storage_damage_is_not_returned_as_an_authorized_link(native):
    write(native)
    with native.f.authority._connect() as connection:
        connection.execute("SET session_replication_role='replica'")
        connection.execute("UPDATE communication_native_links SET link_json=jsonb_set(link_json,'{native_session_ref}',"
                           "'\"tampered-session\"'::jsonb)")
    with pytest.raises(NativeLinkCorrupt):
        native.facade.native_links(PROJECT)


def test_same_admission_provider_replacement_after_proof_rejects_old_registration(native, monkeypatch):
    original = native.registry.prove

    def replace_after_proof(*args):
        result = original(*args)
        native.registry.unregister(PROVIDER, "harness")
        native.registry.register(native.admission, LocalExistingSessionProvider(native.endpoint))
        return result

    monkeypatch.setattr(native.registry, "prove", replace_after_proof)
    with pytest.raises(CommunicationHttpError) as error:
        write(native)
    assert error.value.code == "native_provider_registration_changed"
    for table in ("communication_native_links", "communication_native_link_history", "communication_native_link_requests"):
        assert count(native, table) == 0


def test_registration_replacement_during_real_storage_wait_rolls_back_all_source_facts(native, monkeypatch):
    import runtime.communication_client_native_links as facade_module

    with native.f.authority._connect() as connection:
        adopt_event_storage(connection)
    entered = threading.Event()
    pid = []
    original = facade_module.write_native_link

    def observe_storage(cursor, *args, **kwargs):
        pid.append(cursor.connection.info.backend_pid)
        entered.set()
        return original(cursor, *args, **kwargs)

    monkeypatch.setattr(facade_module, "write_native_link", observe_storage)
    with native.f.authority._connect() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock = "acs-communication-native-links:resource:" + digest([native.f.authority.tenant_id, PROJECT, "link-one"])
        blocker.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock,))
        pending = pool.submit(write, native)
        assert entered.wait(5), "writer never reached actual storage admission"
        waited = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with native.f.authority._connect() as observation:
                waited = observation.execute("SELECT wait_event='advisory' FROM pg_stat_activity WHERE pid=%s", (pid[0],)).fetchone() == (True,)
            if waited:
                break
            time.sleep(0.01)
        assert waited, "writer did not block on the actual durable resource lock"
        native.registry.unregister(PROVIDER, "harness")
        native.registry.register(native.admission, LocalExistingSessionProvider(native.endpoint))
        blocker.commit()
        with pytest.raises(CommunicationHttpError) as error:
            pending.result(timeout=8)
        assert error.value.code == "native_provider_registration_changed"
    for table in ("communication_native_links", "communication_native_link_history", "communication_native_link_requests"):
        assert count(native, table) == 0
    with native.f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_event_intents WHERE kind='native_link.changed'").fetchone() == (0,)


def test_missing_native_metadata_storage_does_not_create_tables_from_a_read(comm):
    source = comm.clients["b"].service.service.authority
    source._communication_native_links_enabled = True
    source._communication_native_link_settings = CommunicationNativeLinkSettings()
    with pytest.raises(SchemaAdoptionError):
        client(comm).native_links(PROJECT)
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT to_regclass('communication_native_links')").fetchone() == (None,)

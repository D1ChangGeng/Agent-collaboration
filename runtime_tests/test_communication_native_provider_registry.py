"""Pure, unmounted registry tests. No PostgreSQL, process, socket or model.

The local fixture uses real Node/Driver SQLite journals, kernel Driver ownership,
profile file validation, LocalNodeEndpoint and NativeDeliveryAdapter. Its already
existing session and Native readback are controlled evidence, not installed-host
qualification. Remote ports are explicitly synthetic admitted extensions.
"""
from __future__ import annotations

import gc
import json
import sqlite3
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from runtime.codex_driver import (
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.delivery_node import LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_provider_registry import (
    LocalExistingSessionProvider,
    NativeProviderRegistry,
    NativeProviderRejected,
    NativeRegistrationFence,
)
from runtime.native_view_models import (
    ExistingSessionProof,
    HostAuthorizationResult,
    HostPermissionBinding,
    NativeHostCaller,
    NativeSelection,
    ProviderAdmission,
)
from runtime.node import NodeJournal
from runtime.receiver_contract import (
    CapabilityScope,
    Observation,
    ReceiverBinding,
    ReceiverSnapshot,
    unknown_capabilities,
)

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = NOW

    def observation_time(self):
        return self.now


@pytest.fixture
def local(tmp_path, monkeypatch):
    clock = Clock()
    executable, schema, home = tmp_path / "controlled-binary", tmp_path / "schema.json", tmp_path / "home"
    executable.write_bytes(b"controlled profile file; never executed")
    schema.write_text("{}", encoding="utf-8")
    home.mkdir()
    config = home / "config.toml"
    config.write_text('default_permissions="fixture"\napproval_policy="never"\n', encoding="utf-8")
    profile = LaunchProfile(str(executable), file_digest(executable), "0.153.2", str(schema), file_digest(schema),
        str(tmp_path), str(home), file_digest(config), "fixture", {})
    node = NodeJournal(tmp_path / "node.sqlite")
    identity = BindingIdentity(node.identity.node_id, node.identity.boot_incarnation, "actual-runtime",
        "configured-capacity", "slot", 3)
    driver_journal = DriverJournal(tmp_path / "driver.sqlite", clock=clock)
    driver = CodexAppServerDriver("actual-driver-binding", profile, driver_journal, identity=identity,
        check_current=lambda *_args: None, clock=clock)
    driver.thread_id = "controlled-existing-native-session"
    reads = []

    def inspect():
        reads.append(True)
        return {"state": "idle", "session_ref": driver.thread_id, "observation": "native_driver_readback"}

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda *_args: pytest.fail("input authorization"),
        inspect_runtime=inspect, configure_runtime=lambda: pytest.fail("prepare_runtime effect"))
    endpoint = LocalNodeEndpoint(node, "scope", "slot", adapter)
    binding = ReceiverBinding(receiver_id="endpoint", actor_address="collaborator:project:slot", binding_epoch=7,
        provider_generation=None, native_session_ref=None, authority_id="actual-authority",
        authority_incarnation="actual-incarnation", execution_host_ref=node.identity.machine_id)
    selection = NativeSelection(tenant_id="tenant", project_id="project", scope_id="scope", agent_slot_id="slot",
        binding=binding, node_id=node.identity.node_id, boot_incarnation=node.identity.boot_incarnation,
        node_binding_revision=None, runtime_id=identity.runtime_id, runtime_binding_revision=None)
    registry = NativeProviderRegistry(clock=clock.observation_time)
    admission = ProviderAdmission(provider_ref="local-provider", native_authority="host-authority", selection=selection)
    provider = LocalExistingSessionProvider(endpoint)
    registry.register(admission, provider)
    for method in ("spawn", "resume", "invoke", "attach"):
        monkeypatch.setattr(driver, method, lambda *_args, **_kwargs: pytest.fail("Native effect called"))
    yield SimpleNamespace(clock=clock, registry=registry, admission=admission, selection=selection,
        provider=provider, endpoint=endpoint, driver=driver, reads=reads, config=config, schema=schema)
    driver.detach_transport()


def prove(f):
    return f.registry.prove("local-provider", "host-authority", f.selection)


def caller(*, slot="viewer-a", **updates):
    return NativeHostCaller(tenant_id="tenant", project_id="project", principal_ref="same-principal",
        actor_address="collaborator:project:" + slot, viewer_key="actual-viewer:" + slot, auth_revision="actual-auth",
        **updates)


def measured(selection, *, now=NOW, until=None, changes=None):
    generation = "controlled-native-generation"
    scope = CapabilityScope(adapter_id="admitted-fixture", adapter_version="1", harness_kind="synthetic",
        harness_version="1", execution_host_ref=selection.host_ref, binary_digest="a" * 64, config_digest="b" * 64,
        connection_epoch=selection.binding.binding_epoch, provider_generation=generation)
    observations = tuple(Observation(axis=axis, knowledge="observed", value=value, source="native_api",
        observed_at=now, expires_at=until or now + timedelta(seconds=20), binding_epoch=selection.binding.binding_epoch,
        provider_generation=generation, evidence_ref="controlled:readback:" + axis, reason_code=None)
        for axis, value in (("connection", "connected"), ("session", "present")))
    value = ReceiverSnapshot(receiver_id=selection.binding.receiver_id, address=selection.binding.actor_address,
        binding_epoch=selection.binding.binding_epoch, revision=9, native_session_ref="controlled-session",
        capability_scope=scope, observations=observations, capabilities=unknown_capabilities(), allowed_actions=())
    return value.model_copy(update=changes or {})


class ControlledPort:
    def __init__(self, snapshot=None, error=None, after=None):
        self.snapshot, self.error, self.after, self.calls = snapshot, error, after, []

    def existing_session(self, selection):
        self.calls.append(selection)
        if self.error:
            raise self.error
        if self.after:
            self.after()
        return self.snapshot or measured(selection)


def remote(f, port=None, authorization_port=None):
    f.registry.register(ProviderAdmission(provider_ref="remote-provider", native_authority="remote-authority",
        selection=f.selection), port, authorization_port=authorization_port)
    return lambda: f.registry.prove("remote-provider", "remote-authority", f.selection)


def test_actual_local_node_adapter_existing_session_path_is_read_only_and_source_bound(local):
    result = prove(local)
    assert result.state == "verified"
    assert result.native_session_ref == local.driver.thread_id
    assert result.provider_generation == result.snapshot.capability_scope.provider_generation
    assert result.host_ref == local.endpoint.identity.machine_id == result.source.host_ref
    assert result.source.selection.binding.authority_incarnation == "actual-incarnation"
    assert result.selection.node_binding_revision is result.selection.runtime_binding_revision is None
    assert result.snapshot.allowed_actions == () and len(local.reads) == 1
    assert result.expires_at == NOW + timedelta(seconds=2)
    assert {o.axis for o in result.snapshot.observations if o.knowledge == "observed"} == {"connection", "session", "input"}
    for path, tables in ((local.endpoint.journal._path, ("journal", "mailbox", "delivery_invocations")),
                         (local.driver.journal.path, ("driver_operations", "driver_events"))):
        with sqlite3.connect(path) as connection:
            assert all(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0 for table in tables)
    assert ExistingSessionProof.model_validate_json(result.model_dump_json()) == result


def test_verified_link_does_not_grant_host_permissions(local):
    assert prove(local).state == "verified"
    for operation in ("read", "watch", "act", "reveal", "prepare_attachment"):
        result = local.registry.authorize_host("local-provider", "host-authority", local.selection, caller(), operation)
        assert result.state == "unsupported" and result.permission is None
        assert result.reason_code == "native_host_authorization_extension_missing"
    assert len(local.reads) == 1


def test_missing_remote_extension_is_specific_and_does_not_disable_actual_local_provider(local):
    result = remote(local)()
    assert result.state == "unsupported" and result.reason_code == "native_host_extension_missing"
    assert result.native_session_ref is result.provider_generation is result.source is None
    assert prove(local).state == "verified"


def test_unregistered_provider_authority_or_brand_never_selects_a_provider(local):
    for provider, authority in (("codex", "host-authority"), ("local-provider", "wrong-authority")):
        result = local.registry.prove(provider, authority, local.selection)
        assert result.state == "unknown" and result.reason_code == "native_provider_not_registered"
    assert local.reads == []


@pytest.mark.parametrize("field,value", [("tenant_id", "other-tenant"), ("scope_id", "other-scope"),
    ("node_id", "other-node"), ("boot_incarnation", "other-boot"), ("node_binding_revision", 4),
    ("runtime_id", "other-runtime"), ("runtime_binding_revision", 5)])
def test_registry_selection_is_exact_and_no_request_can_expand_admission(local, field, value):
    changed = local.selection.model_copy(update={field: value})
    result = local.registry.prove("local-provider", "host-authority", changed)
    assert result.reason_code == "native_provider_selection_changed" and result.native_session_ref is None
    assert local.reads == []


@pytest.mark.parametrize("field,value", [("receiver_id", "other-endpoint"), ("binding_epoch", 8),
    ("authority_id", "other-authority"), ("authority_incarnation", "other-incarnation"),
    ("execution_host_ref", "other-host"), ("provider_generation", "other-generation"),
    ("native_session_ref", "other-session")])
def test_binding_epoch_generation_and_authority_are_part_of_admission(local, field, value):
    changed = local.selection.model_copy(update={"binding": local.selection.binding.model_copy(update={field: value})})
    result = local.registry.prove("local-provider", "host-authority", changed)
    assert result.reason_code == "native_provider_selection_changed" and local.reads == []


def test_project_and_same_principal_slot_do_not_alias_selection(local):
    for project, slot in (("project", "other-slot"), ("other-project", "slot")):
        selected = local.selection.model_copy(update={"project_id": project, "agent_slot_id": slot,
            "binding": local.selection.binding.model_copy(update={"actor_address": f"collaborator:{project}:{slot}"})})
        assert local.registry.prove("local-provider", "host-authority", selected).reason_code == "native_provider_selection_changed"
    assert local.reads == []


def test_registration_cannot_be_silently_replaced_or_auto_built_from_body(local):
    with pytest.raises(NativeProviderRejected, match="already_registered"):
        local.registry.register(local.admission, local.provider)
    with pytest.raises(TypeError, match="typed server"):
        local.registry.register(local.admission.model_dump(mode="json"), local.provider)
    with pytest.raises(TypeError, match="typed Core"):
        local.registry.prove("local-provider", "host-authority", local.selection.model_dump(mode="json"))
    with pytest.raises(TypeError, match="actual configured"):
        LocalExistingSessionProvider(SimpleNamespace(receiver_snapshot=lambda *_: measured(local.selection)))


def test_descriptor_changes_before_or_during_readback_fail_closed(local, monkeypatch):
    actual = local.endpoint.descriptor
    monkeypatch.setattr(local.endpoint, "descriptor", lambda: {**actual(), "node_id": "different-node"})
    assert prove(local).reason_code == "native_endpoint_selection_changed" and local.reads == []
    calls = []

    def descriptor():
        calls.append(True)
        return {**actual(), **({"boot_incarnation": "changed-boot"} if len(calls) > 1 else {})}

    monkeypatch.setattr(local.endpoint, "descriptor", descriptor)
    assert prove(local).reason_code == "native_endpoint_changed_during_readback" and len(local.reads) == 1


def test_local_adapter_lost_claim_and_current_file_damage_cannot_prove_session(local):
    local.config.write_text('default_permissions="fixture"\napproval_policy="never"\n# changed', encoding="utf-8")
    result = prove(local)
    assert result.state == "unknown" and result.native_session_ref is None
    actual_fd = local.driver._claim_fd
    try:
        local.driver._claim_fd = -1
        assert prove(local).state == "unknown"
    finally:
        local.driver._claim_fd = actual_fd


def test_only_local_adapter_contract_is_accepted_for_local_readback(local):
    local.endpoint.driver = SimpleNamespace(evidence_class="synthetic", receiver_snapshot=lambda _binding: measured(local.selection))
    result = prove(local)
    assert result.state == "unknown" and result.reason_code == "native_adapter_contract_unavailable"


@pytest.mark.parametrize("field,value", [("receiver_id", "wrong-receiver"), ("address", "collaborator:project:other"),
    ("native_session_ref", None)])
def test_typed_provider_still_must_prove_exact_source(local, field, value):
    get = remote(local, ControlledPort(measured(local.selection, changes={field: value})))
    result = get()
    assert result.state == "unknown" and result.native_session_ref is result.provider_generation is None


@pytest.mark.parametrize("field,value", [("binary_digest", None), ("config_digest", None),
    ("harness_version", None), ("provider_generation", None), ("execution_host_ref", "wrong-host")])
def test_capability_scope_must_be_complete_and_current(local, field, value):
    snapshot = measured(local.selection)
    scope = snapshot.capability_scope.model_copy(update={field: value})
    snapshot = snapshot.model_copy(update={"capability_scope": scope,
        "observations": tuple(o.model_copy(update={"provider_generation": value}) for o in snapshot.observations)
        if field == "provider_generation" else snapshot.observations})
    result = remote(local, ControlledPort(snapshot))()
    assert result.state == "unknown" and result.source is None


@pytest.mark.parametrize("source,knowledge", [("authority", "observed"), ("pty_heuristic", "inferred")])
def test_configured_session_and_heuristic_evidence_do_not_prove_native_session(local, source, knowledge):
    snapshot = measured(local.selection)
    snapshot = snapshot.model_copy(update={"observations": tuple(o.model_copy(update={"source": source,
        "knowledge": knowledge}) for o in snapshot.observations)})
    assert remote(local, ControlledPort(snapshot))().reason_code == "native_existing_session_unconfirmed"


@pytest.mark.parametrize("timing", ["expired", "future", "missing"])
def test_proof_freshness_is_original_native_readback_not_get_time(local, timing):
    snapshot = measured(local.selection, now=NOW - timedelta(seconds=30))
    if timing == "future":
        snapshot = measured(local.selection, now=NOW + timedelta(seconds=1))
    if timing == "missing":
        snapshot = measured(local.selection)
        snapshot = snapshot.model_copy(update={"observations": tuple(o.model_copy(update={"expires_at": None}) for o in snapshot.observations)})
    result = remote(local, ControlledPort(snapshot))()
    assert result.state == "unknown" and result.observed_at is result.expires_at is result.source is None


def test_ttl_is_bounded_and_expiration_strips_verified_claims(local):
    result = remote(local, ControlledPort())()
    assert result.state == "verified" and result.expires_at == NOW + timedelta(seconds=5)
    current = result.current(NOW + timedelta(seconds=5))
    assert current.state == "unknown" and current.reason_code == "native_proof_expired"
    assert current.native_session_ref is current.provider_generation is current.snapshot is current.source is None
    assert result.native_session_ref == "controlled-session"


def test_shorter_intrinsic_capability_expiry_is_not_extended_by_link_proof(local):
    snapshot = measured(local.selection)
    capabilities = tuple(c.model_copy(update={"support": "supported", "availability": "available",
        "valid_until": NOW + timedelta(seconds=1), "evidence_ref": "controlled:capability"})
        if c.name == "native.transcript_read" else c for c in snapshot.capabilities)
    proof = remote(local, ControlledPort(snapshot.model_copy(update={"capabilities": capabilities})))()
    assert proof.state == "verified"
    current = proof.current(NOW + timedelta(seconds=2))
    assert current.state == "verified" and current.native_session_ref == "controlled-session"
    capability = next(c for c in current.intrinsic_capabilities if c.name == "native.transcript_read")
    assert capability.support == capability.availability == "unknown"


def test_server_refresh_admits_actual_pin_then_native_session_change_invalidates_it(local):
    original = prove(local)
    selected = local.selection.model_copy(update={"binding": local.selection.binding.model_copy(update={
        "native_session_ref": original.native_session_ref, "provider_generation": original.provider_generation})})
    admission = local.admission.model_copy(update={"selection": selected})
    local.registry.unregister("local-provider", "host-authority")
    local.registry.register(admission, local.provider)
    assert local.registry.prove("local-provider", "host-authority", selected).state == "verified"
    local.driver.thread_id = "controlled-different-session"
    changed = local.registry.prove("local-provider", "host-authority", selected)
    assert changed.state == "unknown" and changed.native_session_ref is changed.provider_generation is None


def test_native_driver_identity_change_without_core_rebind_is_rejected(local):
    local.driver.identity = replace(local.driver.identity, node_boot_id="different-node-boot")
    assert prove(local).state == "unknown"


def test_slow_readback_cannot_refresh_expired_native_evidence(local):
    port = ControlledPort(measured(local.selection), after=lambda: setattr(local.clock, "now", NOW + timedelta(seconds=6)))
    assert remote(local, port)().reason_code == "native_proof_expired"


@pytest.mark.parametrize("error,state,reason", [(TimeoutError("secret URL"), "disconnected", "native_host_disconnected"),
    (ValueError("secret token"), "unknown", "native_provider_readback_failed")])
def test_errors_are_typed_and_do_not_leak_provider_details(local, error, state, reason):
    result = remote(local, ControlledPort(error=error))()
    assert result.state == state and result.reason_code == reason and "secret" not in result.model_dump_json()


@pytest.mark.parametrize("knowledge,value,state,reason", [("unsupported", None, "unsupported", "host_session_unsupported"),
    ("observed", "disconnected", "disconnected", "host_offline"), ("unknown", None, "unknown", "host_reason_unknown")])
def test_actual_unknown_unsupported_and_disconnected_reasons_are_preserved(local, knowledge, value, state, reason):
    snapshot = measured(local.selection)
    observation = snapshot.observations[0].model_copy(update={"knowledge": knowledge, "value": value, "reason_code": reason})
    result = remote(local, ControlledPort(snapshot.model_copy(update={"observations": (observation, snapshot.observations[1])})))()
    assert result.state == state and result.reason_code == reason and result.native_session_ref is None


def test_registration_removal_during_readback_invalidates_result(local):
    port = ControlledPort(after=lambda: local.registry.unregister("remote-provider", "remote-authority"))
    assert remote(local, port)().reason_code == "native_provider_registration_changed"


def test_body_schema_does_not_accept_claimed_url_credentials_or_action_fields(local):
    for field in ("url", "credentials", "provider_brand", "transcript", "action"):
        body = local.admission.model_dump(mode="json") | {field: "untrusted"}
        with pytest.raises(ValidationError):
            ProviderAdmission.model_validate_json(__import__("json").dumps(body))
    result = prove(local)
    with pytest.raises(ValidationError):
        result.model_validate_json(result.model_dump_json().replace('"state":"verified"', '"state":"unknown"'))
    assert result.selection.model_config["frozen"] is True


class ControlledHostAuthorization:
    def __init__(self, mutate=None, after=None):
        self.mutate, self.after, self.calls = mutate, after, []

    def authorize(self, actor, source, operation):
        self.calls.append((actor, source, operation))
        binding = HostPermissionBinding(source=source, caller=actor, operation=operation,
            permission_binding_nonce="controlled-host-nonce", issued_at=NOW, expires_at=NOW + timedelta(seconds=2),
            evidence_ref="controlled:host-permission")
        if self.mutate:
            binding = self.mutate(binding)
        if self.after:
            self.after()
        return HostAuthorizationResult(state="authorized", reason_code=None, permission=binding)


def authorize(f, actor=None, operation="read"):
    return f.registry.authorize_host("remote-provider", "remote-authority", f.selection, actor or caller(), operation)


def test_separate_host_port_returns_exact_generation_viewer_nonce_and_operation(local):
    port = ControlledHostAuthorization()
    remote(local, ControlledPort(), port)
    result = authorize(local)
    assert result.state == "authorized"
    assert result.permission.permission_binding_nonce == "controlled-host-nonce"
    assert result.permission.source.provider_generation == "controlled-native-generation"
    assert result.permission.source.host_ref == local.selection.host_ref
    assert result.permission.caller == caller() and result.permission.operation == "read"
    assert port.calls == [(caller(), result.permission.source, "read")]


@pytest.mark.parametrize("change", ["slot", "generation", "operation", "expired", "future"])
def test_host_permission_cannot_move_to_same_principal_other_slot_or_generation(local, change):
    def mutate(binding):
        updates = {"caller": caller(slot="viewer-b")} if change == "slot" else {}
        if change == "generation":
            updates = {"source": binding.source.model_copy(update={"provider_generation": "changed-generation"})}
        if change == "operation":
            updates = {"operation": "act"}
        if change == "expired":
            updates = {"issued_at": NOW - timedelta(seconds=2), "expires_at": NOW}
        if change == "future":
            updates = {"issued_at": NOW + timedelta(seconds=1)}
        return binding.model_copy(update=updates)

    remote(local, ControlledPort(), ControlledHostAuthorization(mutate))
    result = authorize(local)
    assert result.state == "denied" and result.reason_code == "native_host_permission_binding_changed"


def test_host_authorization_cannot_extend_expired_link_proof(local):
    remote(local, ControlledPort(), ControlledHostAuthorization(after=lambda: setattr(local.clock, "now", NOW + timedelta(seconds=6))))
    assert authorize(local).reason_code == "native_proof_expired"


def test_unknown_host_operations_are_typed_unsupported_without_readback(local):
    port = ControlledHostAuthorization()
    remote(local, ControlledPort(), port)
    result = authorize(local, operation="launch-arbitrary")
    assert result.state == "unsupported" and result.permission is None and port.calls == []


def test_host_caller_must_be_typed_and_current_project_matches(local):
    port = ControlledHostAuthorization()
    remote(local, ControlledPort(), port)
    other = caller().model_copy(update={"tenant_id": "other-tenant"})
    assert authorize(local, other).state == "denied" and port.calls == []
    with pytest.raises(TypeError, match="facade-derived"):
        authorize(local, caller().model_dump(mode="json"))


def test_no_fake_defaults_for_native_proof_or_host_permission(local):
    with pytest.raises(ValidationError):
        HostPermissionBinding(source=prove(local).source, caller=caller(), operation="read", issued_at=NOW,
            expires_at=NOW + timedelta(seconds=1), evidence_ref="evidence")
    with pytest.raises(ValidationError):
        ExistingSessionProof(state="verified", reason_code=None, provider_ref="provider", native_authority="authority",
            selection=local.selection, host_ref=local.selection.host_ref)


@pytest.mark.parametrize("ttl", [0, -1, 31, float("nan"), float("inf"), True])
def test_invalid_ttl_cannot_grant_unbounded_freshness(ttl):
    with pytest.raises(ValueError, match="TTL"):
        NativeProviderRegistry(proof_ttl_seconds=ttl)


def core_selection(selection):
    """Only fields the ordinary committed endpoint row actually establishes."""
    return selection.model_copy(update={"node_binding_revision": None, "runtime_id": None,
        "runtime_binding_revision": None, "binding": selection.binding.model_copy(update={
            "provider_generation": None, "native_session_ref": None})})


def test_resolve_unknown_optional_fields_uses_only_existing_server_admission_without_host_reads(local):
    observed = prove(local)
    registered = local.selection.model_copy(update={"node_binding_revision": local.driver.identity.revision,
        "runtime_binding_revision": 9, "binding": local.selection.binding.model_copy(update={
            "provider_generation": observed.provider_generation, "native_session_ref": observed.native_session_ref})})
    local.registry.unregister("local-provider", "host-authority")
    local.registry.register(local.admission.model_copy(update={"selection": registered}), local.provider)
    actual = core_selection(registered)
    before = list(local.reads)
    # Proof's strict selection check is not relaxed by the metadata resolver.
    assert local.registry.prove("local-provider", "host-authority", actual).reason_code == "native_provider_selection_changed"
    resolved = local.registry.resolve("local-provider", "host-authority", actual)
    assert local.reads == before and resolved.selection == registered and actual.runtime_id is None
    assert resolved.selection.runtime_binding_revision == 9
    assert resolved.selection.binding.provider_generation == observed.provider_generation
    assert local.registry.prove(resolved.provider_ref, resolved.native_authority, resolved.selection).state == "verified"
    assert len(local.reads) == len(before) + 1


@pytest.mark.parametrize("field,value", [("tenant_id", "another-tenant"), ("project_id", "another-project"),
    ("scope_id", "another-scope"), ("agent_slot_id", "another-slot"), ("node_id", "another-node"),
    ("boot_incarnation", "another-boot")])
def test_resolve_requires_all_mandatory_outer_core_fields(local, field, value):
    actual = core_selection(local.selection).model_copy(update={field: value})
    if field in {"project_id", "agent_slot_id"}:
        actual = actual.model_copy(update={"binding": actual.binding.model_copy(update={
            "actor_address": f"collaborator:{actual.project_id}:{actual.agent_slot_id}"})})
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.resolve("local-provider", "host-authority", actual)
    assert caught.value.code == "native_provider_selection_changed" and local.reads == []


@pytest.mark.parametrize("field,value", [("receiver_id", "another-receiver"), ("binding_epoch", 8),
    ("authority_id", "another-authority"), ("authority_incarnation", "another-incarnation"),
    ("execution_host_ref", "another-host")])
def test_resolve_requires_all_mandatory_bound_receiver_fields(local, field, value):
    actual = core_selection(local.selection)
    actual = actual.model_copy(update={"binding": actual.binding.model_copy(update={field: value})})
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.resolve("local-provider", "host-authority", actual)
    assert caught.value.code == "native_provider_selection_changed" and local.reads == []


def test_resolve_revalidates_address_and_model_copy_before_using_registry(local):
    actual = local.selection.model_copy(update={"binding": local.selection.binding.model_copy(update={
        "actor_address": "collaborator:project:another-slot"})})
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.resolve("local-provider", "host-authority", actual)
    assert caught.value.code == "native_provider_selection_invalid"
    with pytest.raises(TypeError, match="typed Core"):
        local.registry.resolve("local-provider", "host-authority", core_selection(local.selection).model_dump(mode="json"))
    assert local.reads == []


@pytest.mark.parametrize("field,value", [("node_binding_revision", 2), ("runtime_id", "conflicting-runtime"),
    ("runtime_binding_revision", 2), ("provider_generation", "conflicting-generation"),
    ("native_session_ref", "conflicting-session")])
def test_resolve_never_overrides_a_known_optional_actual_value(local, field, value):
    actual = local.selection
    if field in {"provider_generation", "native_session_ref"}:
        actual = actual.model_copy(update={"binding": actual.binding.model_copy(update={field: value})})
    else:
        actual = actual.model_copy(update={field: value})
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.resolve("local-provider", "host-authority", actual)
    assert caught.value.code == "native_provider_optional_selection_changed" and local.reads == []


def test_resolve_known_optional_equality_and_unknown_admission_stay_honest(local):
    exact = local.registry.resolve("local-provider", "host-authority", local.selection)
    assert exact == local.admission and exact is not local.admission
    assert exact.selection.node_binding_revision is exact.selection.binding.provider_generation is None
    assert exact.selection.runtime_id == "actual-runtime"
    assert local.reads == []


@pytest.mark.parametrize("provider,authority", [("not-admitted", "host-authority"),
    ("local-provider", "another-authority"), ("codex", "harness")])
def test_resolve_unregistered_or_brand_selection_is_explicitly_rejected(local, provider, authority):
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.resolve(provider, authority, core_selection(local.selection))
    assert caught.value.code == "native_provider_not_registered" and local.reads == []


def test_resolve_returns_an_owned_immutable_copy_and_cannot_mutate_registration(local):
    actual = core_selection(local.selection)
    resolved = local.registry.resolve("local-provider", "host-authority", actual)
    with pytest.raises(ValidationError):
        resolved.selection.binding.binding_epoch = 99
    # Deliberate Python-level corruption of the returned copy cannot change the
    # server admission or turn strict proof lookup into a rebind permission.
    object.__setattr__(resolved.selection.binding, "binding_epoch", 99)
    assert local.registry.resolve("local-provider", "host-authority", actual).selection.binding.binding_epoch == 7
    assert local.registry.prove("local-provider", "host-authority", resolved.selection).reason_code == "native_provider_selection_changed"
    assert local.reads == []


def test_resolve_then_registry_replacement_cannot_follow_a_new_binding(local):
    actual = core_selection(local.selection)
    resolved = local.registry.resolve("local-provider", "host-authority", actual)
    changed = local.selection.model_copy(update={"binding": local.selection.binding.model_copy(update={"binding_epoch": 8})})
    local.registry.unregister("local-provider", "host-authority")
    local.registry.register(local.admission.model_copy(update={"selection": changed}), local.provider)
    assert local.registry.prove("local-provider", "host-authority", resolved.selection).reason_code == "native_provider_selection_changed"
    with pytest.raises(NativeProviderRejected, match="selection_changed"):
        local.registry.resolve("local-provider", "host-authority", actual)
    assert local.reads == []


def test_resolve_waiting_for_concurrent_registry_change_compares_current_admission(local):
    actual = core_selection(local.selection)
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        with local.registry._lock:
            future = executor.submit(local.registry.resolve, "local-provider", "host-authority", actual)
            local.registry.unregister("local-provider", "host-authority")
            changed = local.selection.model_copy(update={"boot_incarnation": "replacement-boot"})
            local.registry.register(local.admission.model_copy(update={"selection": changed}), local.provider)
        with pytest.raises(NativeProviderRejected, match="selection_changed"):
            future.result(timeout=2)
    finally:
        executor.shutdown(wait=True)
    assert local.reads == []


def test_resolve_missing_host_extension_grants_no_proof_or_host_permission(local):
    remote(local)
    resolved = local.registry.resolve("remote-provider", "remote-authority", core_selection(local.selection))
    assert resolved.selection.runtime_id == "actual-runtime" and not hasattr(resolved, "permission")
    assert local.registry.prove(resolved.provider_ref, resolved.native_authority, resolved.selection).state == "unsupported"
    assert local.registry.authorize_host(resolved.provider_ref, resolved.native_authority, resolved.selection,
        caller(), "read").state == "unsupported"
    assert local.reads == []


def test_fenced_resolution_is_owned_metadata_with_no_host_clock_or_permission_calls(local):
    local.registry.clock = lambda: pytest.fail("registration fence consulted Host/proof clock")
    admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    assert admission == local.admission and admission is not local.admission
    assert admission.selection is not local.admission.selection
    assert local.registry.assert_current(fence) is None and local.reads == []
    assert not hasattr(fence, "provider_generation") and not hasattr(fence, "permission")
    with pytest.raises(TypeError):
        json.dumps(fence)


@pytest.mark.parametrize("replacement", ["same_provider", "new_provider", "removed"])
def test_fence_rejects_replacement_before_proof_even_for_equal_admission(local, replacement):
    admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    local.registry.unregister("local-provider", "host-authority")
    if replacement != "removed":
        provider = local.provider if replacement == "same_provider" else LocalExistingSessionProvider(local.endpoint)
        local.registry.register(admission, provider)
        assert local.registry.resolve("local-provider", "host-authority", core_selection(local.selection)) == admission
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.assert_current(fence)
    assert caught.value.code == "native_provider_registration_changed" and local.reads == []


def test_replacement_during_proof_invalidates_both_proof_and_registration_fence(local):
    port = ControlledPort()
    remote(local, port)
    admission, fence = local.registry.resolve_fenced("remote-provider", "remote-authority", core_selection(local.selection))

    def replace_registration():
        local.registry.unregister("remote-provider", "remote-authority")
        local.registry.register(admission, ControlledPort())

    port.after = replace_registration
    result = local.registry.prove(admission.provider_ref, admission.native_authority, admission.selection)
    assert result.state == "unknown" and result.reason_code == "native_provider_registration_changed"
    with pytest.raises(NativeProviderRejected, match="registration_changed"):
        local.registry.assert_current(fence)
    assert len(port.calls) == 1 and local.reads == []


def test_replacement_after_verified_proof_rejects_old_fence_without_rewriting_native_generation(local):
    admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    original = local.registry.prove(admission.provider_ref, admission.native_authority, admission.selection)
    assert original.state == "verified"
    generation = original.provider_generation
    local.registry.unregister("local-provider", "host-authority")
    local.registry.register(admission, local.provider)
    with pytest.raises(NativeProviderRejected, match="registration_changed"):
        local.registry.assert_current(fence)
    current_admission, current_fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    current = local.registry.prove(current_admission.provider_ref, current_admission.native_authority, current_admission.selection)
    assert local.registry.assert_current(current_fence) is None
    assert current.provider_generation == generation == original.provider_generation
    assert current.native_session_ref == original.native_session_ref and len(local.reads) == 2


def test_unrelated_provider_registration_does_not_invalidate_fence(local):
    _admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    remote(local)
    assert local.registry.assert_current(fence) is None
    local.registry.unregister("remote-provider", "remote-authority")
    assert local.registry.assert_current(fence) is None and local.reads == []


@pytest.mark.parametrize("forged", [None, {}, {"registry": "local-provider"}, "opaque-string", b"opaque-bytes"])
def test_http_shaped_fence_forgeries_are_never_admitted(local, forged):
    with pytest.raises(NativeProviderRejected) as caught:
        local.registry.assert_current(forged)
    assert caught.value.code == "native_provider_fence_invalid" and local.reads == []


def test_unminted_typed_fence_and_other_registry_cannot_impersonate_owner(local):
    with pytest.raises(NativeProviderRejected, match="fence_invalid"):
        local.registry.assert_current(NativeRegistrationFence())
    _admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    another = NativeProviderRegistry()
    another.register(local.admission, local.provider)
    with pytest.raises(NativeProviderRejected, match="fence_invalid"):
        another.assert_current(fence)
    assert local.registry.assert_current(fence) is None and local.reads == []


def test_mutating_owned_fenced_admission_does_not_change_fence_or_registered_selection(local):
    actual = core_selection(local.selection)
    admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", actual)
    object.__setattr__(admission.selection.binding, "binding_epoch", 99)
    assert local.registry.assert_current(fence) is None
    assert local.registry.resolve("local-provider", "host-authority", actual).selection.binding.binding_epoch == 7
    assert local.registry.prove("local-provider", "host-authority", admission.selection).state == "unknown"
    assert local.reads == []


def test_fence_lifetime_does_not_leak_one_registry_record_per_request(local):
    _admission, fence = local.registry.resolve_fenced("local-provider", "host-authority", core_selection(local.selection))
    reference = weakref.ref(fence)
    assert len(local.registry._fences) == 1
    del fence
    gc.collect()
    assert reference() is None and len(local.registry._fences) == 0

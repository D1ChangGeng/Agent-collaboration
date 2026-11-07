"""Receiver continuity using real key/config types and explicit synthetic HTTPS responses."""
from __future__ import annotations

import copy
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime import machine_connections, remote_endpoint
from runtime.connection_clock import ConnectionClock
from runtime.machine_connections import ConfiguredRemoteEndpoint
from runtime.receiver_config import (
    ReceiverClientConfig,
    ReceiverRuntimeConfig,
    receiver_clock_identity,
)
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign
from runtime.receiver_models import EndpointBinding, EndpointRegistration, ReadbackBody
from runtime.remote_endpoint import (
    PEER_PROTOCOL,
    ReceiverHandler,
    RemoteNodeTransport,
    RemotePeerChanged,
    RemoteTransportRejected,
    receiver_peer_identity,
)
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime.surface_config import RemoteEndpointSettings


@pytest.fixture
def peer(monkeypatch):
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    registration = EndpointRegistration(registration_id="registration", endpoint_id="endpoint", endpoint_revision=1,
        connection_ref="connection", tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        node_id="node", node_binding_revision=1, runtime_id="runtime", runtime_revision=1, machine_id="machine",
        boot_incarnation="boot", scope_id="scope", agent_slot_id="slot", tls_certificate_sha256=sha256(b"synthetic-cert"),
        config_sha256="a" * 64)
    binding = EndpointBinding(registration=registration, locator_host="127.0.0.1", locator_port=44555,
        route_class="loopback", node_key_id="node-key", node_public_key=public_key(node_key),
        registration_signature=sign(node_key, registration))
    config = ReceiverClientConfig(binding=binding, authority_key_id="authority-key", authority_key_revision=1,
        authority_public_key=public_key(authority_key), authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        expected_boot_incarnation="boot", journal_generation=1, access_mode="owner")
    monkeypatch.setenv("ACS_PEER_TEST_KEY", authority_key.encode().hex())
    settings = RemoteEndpointSettings(endpoint_id="endpoint", authority_signing_key_ref={"kind": "environment", "name": "ACS_PEER_TEST_KEY"})
    committed = {"registration": {"endpoint_revision": 1, "registration_sha256": "b" * 64,
        "registration_json": registration.model_dump(mode="json"), "registration_signature": binding.registration_signature,
        "node_key_id": "node-key", "boot_incarnation": "boot"},
        "connection": {"revision": 1, "locator_host": binding.locator_host, "locator_port": binding.locator_port,
            "route_class": binding.route_class, "policy_digest": "c" * 64}, "node_public_key": public_key(node_key)}
    key = {"key_id": config.authority_key_id, "revision": 1, "public_key": config.authority_public_key,
           "fingerprint": config.authority_public_key_fingerprint, "expires_at": None}
    store = SimpleNamespace(load_endpoint=lambda _endpoint: copy.deepcopy(committed), load_authority_key=lambda: dict(key))
    authority = SimpleNamespace(receiver_transport=store, access_mode="owner")
    return SimpleNamespace(config=config, settings=settings, committed=committed, key=key, store=store,
        authority=authority, authority_key=authority_key, node_key=node_key)


def fake_adapter_factory(peer, monkeypatch):
    calls = []

    def create(_authority, _endpoint, deployment, *, timeout):
        marker = {"registration": copy.deepcopy(peer.committed), "authority_key": dict(peer.key),
                  "generation": deployment.journal_generation, "timeout": timeout}
        calls.append(marker)
        row, connection = peer.committed["registration"], peer.committed["connection"]
        registration = EndpointRegistration.model_validate_json(json.dumps(row["registration_json"]), strict=True)
        binding = EndpointBinding(registration=registration, locator_host=connection["locator_host"],
            locator_port=connection["locator_port"], route_class=connection["route_class"], node_key_id=row["node_key_id"],
            node_public_key=peer.committed["node_public_key"], registration_signature=row["registration_signature"])
        config = replace(peer.config, binding=binding, authority_key_id=peer.key["key_id"], authority_key_revision=peer.key["revision"],
            authority_public_key=peer.key["public_key"], authority_public_key_fingerprint=peer.key["fingerprint"],
            expected_boot_incarnation=deployment.expected_boot_incarnation, journal_generation=deployment.journal_generation,
            old_boot_isolation_ref=deployment.old_boot_isolation_ref)
        config.validate()
        return SimpleNamespace(marker=marker, config=config,
                               transport=SimpleNamespace(inspect_runtime=lambda: {"state": "idle"}))

    monkeypatch.setattr(machine_connections, "RemoteNodeEndpointAdapter", create)
    return calls


@pytest.mark.parametrize("area,field,value", [
    ("registration", "endpoint_revision", 2), ("registration", "registration_sha256", "d" * 64),
    ("registration", "boot_incarnation", "new-boot"),
    ("connection", "revision", 2), ("connection", "locator_host", "127.0.0.2"),
    ("connection", "locator_port", 44556), ("connection", "policy_digest", "d" * 64),
    ("registration_json", "node_id", "new-node"), ("registration_json", "node_binding_revision", 2),
    ("registration_json", "runtime_revision", 2), ("registration_json", "tls_certificate_sha256", "d" * 64),
    ("registration_json", "config_sha256", "d" * 64),
])
def test_every_represented_committed_peer_change_invalidates_cached_adapter(peer, monkeypatch, area, field, value):
    calls = fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    original = endpoint._adapter()
    assert endpoint._adapter() is original and len(calls) == 1
    target = peer.committed["registration"]["registration_json"] if area == "registration_json" else peer.committed[area]
    target[field] = value
    if area == "registration" and field in {"endpoint_revision", "boot_incarnation"}:
        peer.committed["registration"]["registration_json"][field] = value
    if area in {"registration", "registration_json"}:
        registration = EndpointRegistration.model_validate_json(json.dumps(peer.committed["registration"]["registration_json"]), strict=True)
        peer.committed["registration"]["registration_signature"] = sign(peer.node_key, registration)
    current = endpoint._adapter()
    assert current is not original and len(calls) == 2


def test_current_authority_key_and_resolved_signing_reference_are_not_cached(peer, monkeypatch):
    calls = fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    original = endpoint._adapter()
    changed = SigningKey.generate()
    peer.key.update(key_id="rotated-key", revision=2, public_key=public_key(changed), fingerprint=key_fingerprint(public_key(changed)))
    with pytest.raises(RemotePeerChanged):
        endpoint._adapter()
    assert endpoint._bound is None and len(calls) == 1
    monkeypatch.setenv("ACS_PEER_TEST_KEY", changed.encode().hex())
    assert endpoint._adapter() is not original and len(calls) == 2


def test_missing_current_authority_key_cannot_fall_back_to_the_cached_peer(peer, monkeypatch):
    fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    endpoint._adapter()
    peer.store.load_authority_key = lambda: None
    result = endpoint.inspect_runtime()
    assert result["state"] == "unknown" and result["peer_verification"] == "changed"
    assert endpoint._bound is endpoint._fingerprint is None


def test_node_key_and_journal_generation_change_invalidate_independently(peer, monkeypatch):
    calls = fake_adapter_factory(peer, monkeypatch)
    selected = {"settings": peer.settings}
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings, settings_provider=lambda _: selected["settings"])
    original = endpoint._adapter()
    peer.node_key = SigningKey.generate()
    peer.committed["node_public_key"] = public_key(peer.node_key)
    peer.committed["registration"]["node_key_id"] = "replacement-node-key"
    peer.committed["registration"]["registration_signature"] = sign(peer.node_key, peer.config.binding.registration)
    second = endpoint._adapter()
    assert second is not original
    selected["settings"] = replace_settings = peer.settings.model_copy(update={"journal_generation": 2,
        "old_boot_isolation_ref": "synthetic-stop-proof"})
    third = endpoint._adapter()
    assert third is not second and calls[-1]["generation"] == replace_settings.journal_generation == 2


def test_lifecycle_control_change_invalidates_cached_peer_without_machine_preparation(peer, monkeypatch):
    calls = fake_adapter_factory(peer, monkeypatch)
    selected = [peer.settings]
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings, settings_provider=lambda _: selected[0])
    monkeypatch.setattr(endpoint, "_prepare", lambda: pytest.fail("settings reload cannot prepare Native"))
    original = endpoint._adapter()
    selected[0] = peer.settings.model_copy(update={"lifecycle_control": True})
    enabled = endpoint._adapter()
    assert enabled is not original and len(calls) == 2
    selected[0] = peer.settings
    assert endpoint._adapter() is not enabled and len(calls) == 3


@pytest.mark.parametrize("disable_during_refresh", [False, True])
def test_configured_lifecycle_disable_fences_both_initial_and_second_refresh(peer, monkeypatch, disable_during_refresh):
    from runtime.receiver_lifecycle_transport import ConfiguredLifecycleTransport

    fake_adapter_factory(peer, monkeypatch)
    enabled = peer.settings.model_copy(update={"lifecycle_control": True})
    reads = []

    def selected(_endpoint):
        reads.append(1)
        return enabled if disable_during_refresh and len(reads) == 1 else peer.settings

    endpoint = ConfiguredRemoteEndpoint(peer.authority, enabled, settings_provider=selected)
    monkeypatch.setattr(endpoint, "_prepare", lambda: pytest.fail("disabled control cannot prepare Native"))
    transport = ConfiguredLifecycleTransport(endpoint)
    with pytest.raises(ValueError, match="disabled"):
        _config = transport.config
    assert len(reads) == (2 if disable_during_refresh else 1)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_lifecycle_control_configuration_requires_a_real_boolean(peer, value):
    with pytest.raises(ValueError):
        RemoteEndpointSettings.model_validate(peer.settings.model_dump() | {"lifecycle_control": value})


def test_change_during_adapter_construction_is_rejected_without_unbounded_rebinding(peer, monkeypatch):
    calls = []

    def changed(*_args, **_kwargs):
        calls.append("constructor")
        peer.committed["connection"]["revision"] += 1
        return SimpleNamespace()

    monkeypatch.setattr(machine_connections, "RemoteNodeEndpointAdapter", changed)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    with pytest.raises(RemotePeerChanged, match="during binding"):
        endpoint._adapter()
    assert calls == ["constructor"] and endpoint._bound is endpoint._fingerprint is None


def test_candidate_without_validated_config_cannot_enter_the_cache(peer, monkeypatch):
    monkeypatch.setattr(machine_connections, "RemoteNodeEndpointAdapter", lambda *_args, **_kwargs: SimpleNamespace())
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    with pytest.raises(RemotePeerChanged):
        endpoint._adapter()
    assert endpoint._bound is endpoint._fingerprint is None


def test_candidate_from_a_transient_different_peer_is_rejected_even_if_source_returns_to_original(peer, monkeypatch):
    registration = peer.config.binding.registration.model_copy(update={"node_id": "transient-node"})
    binding = peer.config.binding.model_copy(update={"registration": registration,
        "registration_signature": sign(peer.node_key, registration)})
    candidate = replace(peer.config, binding=binding)
    candidate.validate()
    monkeypatch.setattr(machine_connections, "RemoteNodeEndpointAdapter", lambda *_args, **_kwargs:
        SimpleNamespace(config=candidate))
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    with pytest.raises(RemotePeerChanged):
        endpoint._adapter()
    assert endpoint._bound is endpoint._fingerprint is None


def test_candidate_with_a_different_authority_mode_cannot_reuse_registered_identity(peer, monkeypatch):
    candidate = replace(peer.config, access_mode="shared")
    candidate.validate()
    monkeypatch.setattr(machine_connections, "RemoteNodeEndpointAdapter", lambda *_args, **_kwargs:
        SimpleNamespace(config=candidate))
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    with pytest.raises(RemotePeerChanged):
        endpoint._adapter()
    assert endpoint._bound is endpoint._fingerprint is None


def test_unknown_registered_schema_version_rejects_old_cache_instead_of_guessing_support(peer, monkeypatch):
    fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    endpoint._adapter()
    peer.committed["registration"]["registration_json"]["schema_version"] = "future-unreviewed-version"
    with pytest.raises(ValueError):
        endpoint._adapter()
    assert endpoint._bound is endpoint._fingerprint is None


def test_failed_refresh_drops_cached_handle_and_read_only_queries_never_prepare(peer, monkeypatch):
    fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    endpoint._adapter()
    monkeypatch.setattr(endpoint, "_prepare", lambda: pytest.fail("read-only discovery cannot prepare a machine"))
    peer.store.load_endpoint = lambda _: (_ for _ in ()).throw(OSError("synthetic Authority read failure"))
    assert endpoint.inspect_runtime()["state"] == "offline"
    assert endpoint._bound is endpoint._fingerprint is None


def test_peer_change_during_health_readback_discards_stale_readiness(peer, monkeypatch):
    fake_adapter_factory(peer, monkeypatch)
    endpoint = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    adapter = endpoint._adapter()

    def changed():
        peer.committed["connection"]["revision"] += 1
        return {"state": "idle", "session_ref": "old-session"}

    adapter.transport.inspect_runtime = changed
    monkeypatch.setattr(endpoint, "_prepare", lambda: pytest.fail("readback cannot prepare"))
    result = endpoint.inspect_runtime()
    assert result["state"] == "unknown" and result["session_ref"] is None
    assert result["peer_verification"] == "changed" and endpoint._bound is None


def test_slow_or_failed_peer_does_not_hold_an_unrelated_endpoint_lock(peer, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    healthy = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    failing = ConfiguredRemoteEndpoint(peer.authority, peer.settings)
    monkeypatch.setattr(healthy, "_adapter", lambda: SimpleNamespace(transport=SimpleNamespace(inspect_runtime=lambda: {"state": "idle"})))

    def slow():
        entered.set()
        assert release.wait(3)
        raise OSError("synthetic peer disconnected")

    monkeypatch.setattr(failing, "_adapter", lambda: SimpleNamespace(transport=SimpleNamespace(inspect_runtime=slow)))
    monkeypatch.setattr(failing, "_prepare", lambda: pytest.fail("read-only discovery cannot prepare"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting = pool.submit(failing.inspect_runtime)
        assert entered.wait(1)
        try:
            assert pool.submit(healthy.inspect_runtime).result(timeout=1)["state"] == "idle"
        finally:
            release.set()
        assert waiting.result(timeout=1)["state"] == "offline"


def connection_fixture(peer, monkeypatch, *, response=None, error=None, delay=0):
    events = []
    response = response if response is not None else {"state": "idle", "harness": "fixture", "version": "1",
        "session_ref": "synthetic-session", "peer_protocol": PEER_PROTOCOL, "peer_identity": receiver_peer_identity(peer.config)}

    class Socket:
        def getpeercert(self, *, binary_form):
            assert binary_form
            return b"synthetic-cert"

        def settimeout(self, value):
            assert 0 < value <= 120

    class Connection:
        sock = None

        def __init__(self, *_args, **_kwargs):
            events.append("construct")

        def connect(self):
            self.sock = Socket()

        def request(self, method, path, **_kwargs):
            events.append((method, path))

        def getresponse(self):
            if error:
                raise error

            def read(_maximum):
                time.sleep(delay)
                return json.dumps(response).encode()

            return SimpleNamespace(status=200, read=read)

        def close(self):
            events.append("close")

    monkeypatch.setattr(remote_endpoint.http.client, "HTTPSConnection", Connection)
    return events


def test_health_readback_requires_actual_peer_context_and_never_posts_input(peer, monkeypatch):
    events = connection_fixture(peer, monkeypatch)
    result = RemoteNodeTransport(peer.config).inspect_runtime()
    assert result["state"] == "idle" and result["peer_verification"] == "current"
    assert [event for event in events if isinstance(event, tuple)] == [("GET", "/healthz")]


def test_legacy_health_without_peer_identity_is_unknown_not_a_current_session(peer, monkeypatch):
    connection_fixture(peer, monkeypatch, response={"state": "idle", "session_ref": "unverified-old-session"})
    result = RemoteNodeTransport(peer.config).inspect_runtime()
    assert result["state"] == "unknown" and result["session_ref"] is None
    assert result["peer_verification"] == "unavailable"


def test_unknown_health_peer_protocol_cannot_reuse_a_matching_identity(peer, monkeypatch):
    connection_fixture(peer, monkeypatch, response={"state": "idle", "peer_protocol": "future-unreviewed-peer/2",
        "peer_identity": receiver_peer_identity(peer.config)})
    with pytest.raises(RemotePeerChanged):
        RemoteNodeTransport(peer.config).inspect_runtime()


@pytest.mark.parametrize("change", ["boot", "journal", "tls", "config", "endpoint", "authority_key", "protocol"])
def test_changed_peer_context_cannot_be_reported_as_ready(peer, monkeypatch, change):
    config = peer.config
    if change == "journal":
        changed = replace(config, journal_generation=2, old_boot_isolation_ref="synthetic-stop")
    elif change == "authority_key":
        changed = replace(config, authority_key_revision=2)
    else:
        fields = {"boot": {"boot_incarnation": "new-boot"}, "tls": {"tls_certificate_sha256": "d" * 64},
                  "config": {"config_sha256": "d" * 64}, "endpoint": {"endpoint_revision": 2}, "protocol": {"schema_version": "future"}}
        registration = config.binding.registration.model_copy(update=fields[change])
        changed = replace(config, binding=config.binding.model_copy(update={"registration": registration}))
    events = connection_fixture(peer, monkeypatch, response={"state": "idle", "peer_protocol": PEER_PROTOCOL,
        "peer_identity": receiver_peer_identity(changed)})
    with pytest.raises(RemotePeerChanged):
        RemoteNodeTransport(config).inspect_runtime()
    assert not any(isinstance(event, tuple) and event[0] == "POST" for event in events)


@pytest.mark.parametrize("change", ["config", "clock", "timeout"])
def test_cached_transport_cannot_mutate_binding_or_clock_before_a_new_request(peer, monkeypatch, change):
    transport = RemoteNodeTransport(peer.config)
    events = connection_fixture(peer, monkeypatch)
    if change == "config":
        transport.config = replace(peer.config, journal_generation=2, old_boot_isolation_ref="synthetic-stop")
    elif change == "clock":
        transport.clock = ConnectionClock.local(reference=lambda: datetime.now(UTC), identity=receiver_clock_identity(peer.config))
    else:
        transport.timeout = float("inf")
    with pytest.raises(RemotePeerChanged):
        transport.inspect_runtime()
    assert events == []


def test_connection_clock_already_prevents_in_place_peer_identity_mutation(peer):
    transport = RemoteNodeTransport(peer.config)
    with pytest.raises(TypeError):
        transport.clock.identity["boot_incarnation"] = "different-boot"
    assert transport.clock.identity["boot_incarnation"] == "boot"


def test_actual_health_handler_adds_opaque_common_context_without_server_private_paths(peer):
    config = peer.config
    runtime = ReceiverRuntimeConfig(binding=config.binding, authority_key_id=config.authority_key_id,
        authority_key_revision=config.authority_key_revision, authority_public_key=config.authority_public_key,
        authority_public_key_fingerprint=config.authority_public_key_fingerprint,
        expected_boot_incarnation=config.expected_boot_incarnation, journal_generation=config.journal_generation,
        access_mode=config.access_mode, tls_cert_path="synthetic-private-cert", tls_key_path="synthetic-private-key",
        node_signing_key_path="synthetic-private-node-key", ledger_path="synthetic-private-ledger")
    handler = object.__new__(ReceiverHandler)
    handler.path = "/healthz"
    handler.server = SimpleNamespace(config=runtime, _native_invoke=lambda *_args: pytest.fail("health cannot invoke Native"))
    handler.send_response = lambda _status: None
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    handler.do_GET()
    body = json.loads(handler.wfile.getvalue())
    assert body["peer_identity"] == receiver_peer_identity(config)
    assert body["peer_protocol"] == PEER_PROTOCOL and body["state"] == "online"
    assert "synthetic-private" not in handler.wfile.getvalue().decode()


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), 121])
def test_transport_timeout_is_finite_and_bounded(peer, timeout):
    with pytest.raises(ValueError, match="timeout"):
        RemoteNodeTransport(peer.config, timeout=timeout)


def test_slow_health_response_cannot_extend_its_original_deadline(peer, monkeypatch):
    events = connection_fixture(peer, monkeypatch, delay=0.02)
    with pytest.raises(TimeoutError):
        RemoteNodeTransport(peer.config, timeout=0.005).inspect_runtime()
    assert events.count(("GET", "/healthz")) == 1 and events[-1] == "close"


def test_unknown_post_ack_is_not_retransmitted_by_transport_or_health_reconnect(peer, monkeypatch):
    transport = RemoteNodeTransport(peer.config)
    identity = DeliveryIdentity("message", "command", "operation", "attempt", "dispatch", None,
        "a" * 64, "b" * 64, "c" * 64, "d" * 64, None)
    request = AdmissionFactory(peer.config, peer.authority_key, identity, clock=transport.clock).request(
        "delivery.readback", ReadbackBody(operation_id="operation", dispatch_id="dispatch"))
    first = connection_fixture(peer, monkeypatch, error=OSError("synthetic ACK disconnected"))
    with pytest.raises(RemoteTransportRejected):
        transport.send(request)
    assert sum(isinstance(event, tuple) and event[0] == "POST" for event in first) == 1
    second = connection_fixture(peer, monkeypatch)
    assert transport.inspect_runtime()["peer_verification"] == "current"
    assert [event for event in second if isinstance(event, tuple)] == [("GET", "/healthz")]

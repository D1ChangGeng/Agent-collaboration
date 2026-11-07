"""E1 controller integration: real crypto/SQLite/Driver guards, controlled Native APIs.

No process, socket, PG, Host or model is contacted. Core authority/snapshot ports
and Native protocol responses are explicit doubles, not external qualification.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime.codex_driver import AuthorizedOperation, CodexAppServerDriver, DriverRejected
from runtime.connection_clock import ConnectionClock
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign, verify
from runtime.receiver_lifecycle_capacity import capture_capacity_profile
from runtime.receiver_lifecycle_contract import (
    LifecycleChallenge,
    LifecyclePermit,
    LifecycleSource,
    build_lifecycle_plan,
    lifecycle_plan_digest,
    sign_challenge,
    sign_observation,
    sign_permit,
)
from runtime.receiver_lifecycle_domain import LifecycleAuthorityKey, LifecycleEndpointSnapshot
from runtime.receiver_lifecycle_node import LifecycleNodeRejected, ReceiverLifecycleNode
from runtime.receiver_lifecycle_read import AuthorizedLifecycleObservation
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.supervisor import OwnedProcess
from runtime_tests.test_receiver_lifecycle_capacity import BINDING, PRIVATE, existing, file_hash
from runtime_tests.test_receiver_lifecycle_capacity import capacity as capacity_fixture

capacity = capacity_fixture
SCHEMAS = Path(__file__).parent


@pytest.fixture
def node(capacity):
    driver = capacity.driver
    schema = SCHEMAS / ("schema-0.153.2/codex_app_server_protocol.schemas.json" if isinstance(driver, CodexAppServerDriver)
                        else "schema-1.18.27/opencode-openapi.json")
    capacity.schema.write_bytes(schema.read_bytes())
    driver.profile = replace(driver.profile, schema_sha256=file_hash(capacity.schema))
    monotonic = [100.0]
    identity = {"authority_id": "authority", "authority_incarnation": "incarnation", "node_id": BINDING.node_id,
        "boot_incarnation": BINDING.node_boot_id, "machine_id": "machine", "endpoint_id": "receiver"}
    clock = ConnectionClock.local(lambda: capacity.driver_time.now, identity=identity,
        monotonic=lambda: monotonic[0], wall=lambda: capacity.driver_time.now)
    driver_time = driver.clock
    capacity.driver_time = driver_time
    driver.clock = driver.journal.clock = clock
    capacity.witness = capture_capacity_profile(driver, authorize_current=capacity.authorize,
        account_fingerprint=capacity.account_reader)
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    registration = EndpointRegistration(registration_id="registration", endpoint_id="receiver", endpoint_revision=5,
        connection_ref="connection", tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        node_id=BINDING.node_id, node_binding_revision=BINDING.revision, runtime_id=BINDING.runtime_id, runtime_revision=4,
        machine_id="machine", boot_incarnation=BINDING.node_boot_id, scope_id="scope", agent_slot_id=BINDING.agent_slot_id,
        tls_certificate_sha256="1" * 64, config_sha256="2" * 64)
    binding = EndpointBinding(registration=registration, locator_host="127.0.0.1", locator_port=12345,
        route_class="loopback", node_key_id="node-key", node_public_key=public_key(node_key),
        registration_signature=sign(node_key, registration))
    config = ReceiverClientConfig(binding, "authority-key", 2, public_key(authority_key),
        key_fingerprint(public_key(authority_key)), BINDING.node_boot_id, 1)
    snapshot = LifecycleEndpointSnapshot(binding, 9, 7, "3" * 64,
        LifecycleAuthorityKey("authority-key", 2, public_key(authority_key), key_fingerprint(public_key(authority_key))),
        1, driver_time.now, driver_time.now + timedelta(minutes=10))
    source = LifecycleSource(operation_ref="original-recovery", command_id="original-core-command", tenant_id="tenant",
        authority_id="authority", authority_incarnation="incarnation", project_id="project", actor_address="slot:original-actor",
        principal_ref="principal", grant_ref="original-core-grant", profile="original-profile", command_digest="4" * 64,
        issuer_context_digest="5" * 64, request_digest="6" * 64)
    state = SimpleNamespace(driver=driver, capacity=capacity, key=authority_key, node_key=node_key, config=config,
        snapshot=snapshot, source=source, core_allowed=True, read_allowed=True, marker=True, permit=None,
        native_calls=[], effects=[], core_calls=[], read_calls=[], capabilities=[], request_hook=None,
        failure=None, monotonic=monotonic, clock=clock, driver_time=driver_time, core_hook=None, process_record_birth=None)
    driver.check_current = lambda operation, actual: state.core_calls.append(("ordinary", operation, actual))
    driver.supervisor.launch = lambda *_args, **_kwargs: pytest.fail("actual process launch is forbidden")

    class Client:
        endpoint = "controlled-no-network"

        def request(self, method, params=None, payload=None, **options):
            before, dispatch = options.get("before_send"), options.get("on_dispatch")
            if before:
                before()
            if state.request_hook:
                state.request_hook(method, params)
            if before:
                before()
            if dispatch:
                dispatch()
            state.native_calls.append((method, params))
            if isinstance(driver, CodexAppServerDriver):
                if method in {"thread/read", "thread/start", "thread/resume"}:
                    return {"thread": {"id": driver.thread_id or "thread_current", "sessionId": driver.session_id or "provider_current",
                        "status": {"type": "idle"}}, "cwd": driver.profile.cwd}
                if method == "thread/turns/list":
                    return {"data": []}
                pytest.fail("unexpected controlled RPC " + method)
            path = params
            if method == "POST" and path == "/session":
                return 200, session("ses_current")
            values = {"/doc": json.loads(capacity.schema.read_text()), "/config": {"provider": {"private": PRIVATE}},
                "/session/status": {driver.session_id: {"type": "idle"}}, "/permission": [], "/question": [],
                "/session/" + (driver.session_id or "ses_current") + "/message": [],
                "/session/" + (driver.session_id or "ses_current"): session(driver.session_id or "ses_current")}
            assert method == "GET", "no input HTTP route is permitted"
            return 200, values[path]

        def drain_events(self):
            return []

        def diagnostics(self):
            return {"controlled": True}

    def session(selected):
        return {"id": selected, "directory": driver.profile.cwd,
            "metadata": {"acs_binding_id": driver.binding_id, "acs_binding": asdict(driver.identity),
                "acs_operation_id": "original-owned-process"}}

    state.client = Client()

    def resolve(stage, requested):
        state.core_calls.append((stage, requested))
        if state.core_hook:
            state.core_hook(stage)
        if not state.core_allowed:
            raise PermissionError("private Core denial")
        return state.source, state.snapshot

    def require(signed):
        if state.core_hook:
            state.core_hook("execute")
        if not state.core_allowed or not state.marker or signed != state.permit:
            raise PermissionError("original committed execution marker is unavailable")

    def read(signed):
        state.read_calls.append(signed)
        if not state.read_allowed or signed != state.permit:
            raise PermissionError("current original-scope read authority is unavailable")
        return state.source

    def start_existing():
        existing(capacity)
        driver.owned.process.poll = lambda: None
        driver.client = state.client
        if not isinstance(driver, CodexAppServerDriver):
            driver.session_id = "ses_current"
            driver.observe_events = False

    state.start_existing = start_existing

    def controlled_spawn(operation):
        def perform():
            state.capabilities.append(operation)
            state.effects.append("spawn")
            driver.journal.event(operation.operation_id, "process_dispatch", {"binding": asdict(driver.identity)})
            driver.owned = OwnedProcess(SimpleNamespace(pid=49152, poll=lambda: None), "actual-controlled-job", "actual-controlled-birth")
            driver.client, driver.ownership = state.client, "exclusive_owned"
            driver.journal.event(operation.operation_id, "process_started", {"pid": 49152,
                "birth_ref": state.process_record_birth or "actual-controlled-birth", "containment_id": "actual-controlled-job"})
            if isinstance(driver, CodexAppServerDriver):
                response = driver._rpc(operation, "thread/start", {"cwd": driver.profile.cwd})
                driver.thread_id, driver.session_id = response["thread"]["id"], response["thread"]["sessionId"]
                result = driver._binding_receipt("runtime_acknowledged")
            else:
                _status, value = driver._http(operation, "POST", "/session", {})
                driver.session_id = value["id"]
                result = driver._receipt("runtime_acknowledged", native_ack_type="session_create_response")
            if state.failure:
                raise state.failure
            return result
        return driver._run(operation, "spawn", {"profile": driver.profile.binding()}, perform)

    driver.spawn = controlled_spawn
    # Restore the real resume method disabled by the capacity fixture's mutation tripwires.
    driver.resume = type(driver).resume.__get__(driver)
    controller = ReceiverLifecycleNode(driver, config, node_key, clock=clock, resolve_original=resolve,
        require_current_execution=require, resolve_original_read=read, profile_witness=capacity.witness,
        reservation_witness=capacity.reservation)
    state.controller, state.resolve, state.require, state.read = controller, resolve, require, read

    def prepare(action="spawn"):
        challenge = LifecycleChallenge(source=state.source, target=state.snapshot.target(), authority_key_id=config.authority_key_id,
            authority_key_revision=config.authority_key_revision, request_id="original-challenge", nonce="7" * 64,
            issued_at=driver_time.now, deadline=driver_time.now + timedelta(seconds=25))
        signed_challenge = sign_challenge(challenge, state.key)
        observation = controller.observe(signed_challenge)
        plan = build_lifecycle_plan(challenge, observation.observation, action)
        permit = LifecyclePermit(plan=plan, semantic_digest=lifecycle_plan_digest(plan), challenge_digest=sha256(challenge),
            observation_digest=sha256(observation.observation), authority_key_id=config.authority_key_id,
            authority_key_revision=config.authority_key_revision, request_id=challenge.request_id, nonce=challenge.nonce,
            issued_at=driver_time.now, deadline=driver_time.now + timedelta(seconds=2))
        state.challenge, state.observation, state.permit = signed_challenge, observation, sign_permit(permit, state.key)
        return state.permit

    state.prepare = prepare
    state.execute = lambda: controller.execute(state.permit, challenge=state.challenge, observation=state.observation)
    state.reconcile = lambda: controller.reconcile(state.permit, challenge=state.challenge, observation=state.observation)
    try:
        yield state
    finally:
        controller.close()


def test_signed_fresh_observation_and_actual_driver_journal_spawn_receipt(node):
    node.prepare()
    assert node.observation.observation.capacity.state == "fresh"
    result = node.execute()
    assert result.receipt.outcome == "acknowledged" and result.receipt.effect_possible
    assert node.effects == ["spawn"] and result.receipt.native_session_ref
    verify(node.config.binding.node_public_key, result.signature, result.receipt)
    row = node.driver.journal.read(node.permit.permit.plan.driver_operation_id)
    assert row["state"] == "acknowledged" and "message_id" not in row["input"]
    assert PRIVATE not in result.model_dump_json()


def test_existing_native_probe_uses_real_message_less_read_capability_and_resume(node):
    node.start_existing()
    node.prepare("resume")
    assert node.observation.observation.capacity.state == "existing" and node.native_calls
    result = node.execute()
    assert result.receipt.outcome == "acknowledged" and result.receipt.native_session_ref == node.permit.permit.plan.capacity.native_session_ref
    assert node.effects == [] and PRIVATE not in node.observation.model_dump_json()
    with node.driver.journal._connect() as connection:
        rows = connection.execute("SELECT message_id,source_kind FROM driver_operations").fetchall()
    assert all(message is None and kind == "receiver_lifecycle" for message, kind in rows)


def test_exact_original_ack_survives_expiry_and_new_core_epoch_without_reentry(node):
    node.prepare(); first = node.execute()
    assert first.receipt.outcome == "acknowledged"
    before = len(node.native_calls)
    node.driver_time.now += timedelta(minutes=1); node.monotonic[0] += 60
    node.snapshot = replace(node.snapshot, binding_epoch=node.snapshot.binding_epoch + 1)
    node.core_allowed = False  # Mutable target authority is unavailable; distinct original read remains valid.
    result = node.execute()
    assert result.receipt.outcome == "acknowledged" and result.receipt.provider_generation == first.receipt.provider_generation
    assert node.effects == ["spawn"] and len(node.native_calls) == before


def test_unknown_after_possible_effect_never_reenters_or_submits_another_session(node):
    node.prepare(); node.failure = OSError("controlled effect settlement lost")
    first = node.execute()
    assert first.receipt.outcome == "unknown" and first.receipt.effect_possible
    before = len(node.native_calls)
    node.failure = None
    second = node.execute()
    assert second.receipt.outcome == "unknown" and node.effects == ["spawn"] and len(node.native_calls) == before


@pytest.mark.parametrize("change", ["marker", "profile", "account", "epoch", "connection", "key", "grant"])
def test_current_core_and_profile_fences_precede_any_driver_effect(node, change):
    node.prepare()
    if change == "marker":
        node.marker = False
    elif change == "profile":
        node.driver.profile.environment["changed"] = "new"
    elif change == "account":
        node.capacity.account = "9" * 64
    elif change == "epoch":
        node.snapshot = replace(node.snapshot, binding_epoch=node.snapshot.binding_epoch + 1)
    elif change == "connection":
        node.snapshot = replace(node.snapshot, connection_revision=node.snapshot.connection_revision + 1)
    elif change == "key":
        node.snapshot = replace(node.snapshot, authority_key=replace(node.snapshot.authority_key, public_key=public_key(SigningKey.generate())))
    else:
        node.core_allowed = False
    try:
        result = node.execute()
    except (DriverRejected, PermissionError):
        pass
    else:
        assert result.receipt.outcome == "definitively_not_started" and not result.receipt.effect_possible
    assert node.effects == [] and node.native_calls == []


def test_missing_profile_or_reservation_signs_unknown_without_native_contact(node):
    node.controller.profile_witness = None
    challenge = LifecycleChallenge(source=node.source, target=node.snapshot.target(), authority_key_id=node.config.authority_key_id,
        authority_key_revision=node.config.authority_key_revision, request_id="unknown", nonce="8" * 64,
        issued_at=node.driver_time.now, deadline=node.driver_time.now + timedelta(seconds=10))
    observed = node.controller.observe(sign_challenge(challenge, node.key))
    assert observed.observation.capacity.state == "unknown" and node.native_calls == [] and node.effects == []


@pytest.mark.parametrize("part", ["permit", "challenge", "observation"])
def test_bad_signature_and_foreign_original_artifacts_cannot_reach_driver(node, part):
    node.prepare()
    value = getattr(node, part)
    changed = value.model_copy(update={"signature": "0" * 128})
    setattr(node, part, changed)
    with pytest.raises(ValueError):
        node.execute()
    assert node.effects == [] and node.native_calls == []


def test_historical_read_requires_current_original_scope_authority(node):
    node.prepare(); node.execute()
    before = len(node.native_calls); node.read_allowed = False
    with pytest.raises(PermissionError):
        node.reconcile()
    assert len(node.native_calls) == before and node.effects == ["spawn"]


def test_retired_exact_mutation_capability_and_naked_read_capability_are_denied(node):
    node.prepare(); node.execute()
    operation = node.capabilities[0]
    with pytest.raises(DriverRejected):
        node.driver.check_current(operation, node.driver.identity)
    selected = node.controller._session()
    generation = node.permit.permit.plan.capacity.provider_generation
    read = AuthorizedLifecycleObservation("receiver-lifecycle-read:" + "1" * 64, node.source.command_id,
        node.source.operation_ref, node.source.grant_ref, node.driver_time.now + timedelta(seconds=10), node.driver.binding_id,
        node.driver.identity, selected, generation, lambda *_args: None)
    with pytest.raises(DriverRejected):
        node.driver.check_current(read, node.driver.identity)


def test_read_capability_rejects_mutation_and_foreign_native_session_routes(node):
    node.start_existing(); node.prepare("resume")
    with node.controller._lease(node.source, node.snapshot.target(), node.driver_time.now + timedelta(seconds=2), "challenge") as read:
        assert not hasattr(read, "message_id") and read.read_only
        with pytest.raises(DriverRejected):
            node.driver._run(read, "resume", {}, lambda: pytest.fail("read capability reached mutation"))
        if isinstance(node.driver, CodexAppServerDriver):
            for method, params in (("turn/start", {}), ("thread/resume", {}), ("thread/read", {"threadId": "foreign"})):
                with pytest.raises(DriverRejected):
                    node.driver._rpc(read, method, params)
        else:
            for method, path in (("POST", "/session"), ("GET", "/session/ses_foreign"), ("GET", "/session")):
                with pytest.raises(DriverRejected):
                    node.driver._http(read, method, path)


def test_driver_ordinary_message_authorizer_survives_controller_and_close_revokes_only_leases(node):
    ordinary = AuthorizedOperation("ordinary", "ordinary-command", "ordinary-message", "ordinary-grant", None)
    node.driver.check_current(ordinary, node.driver.identity)
    assert node.core_calls[-1][0] == "ordinary"
    token = node.driver._claim_token
    node.controller.close()
    node.driver.journal.validate_claim(token, node.driver.binding_id, node.driver._claim_fd)
    node.driver.check_current(ordinary, node.driver.identity)
    with pytest.raises(LifecycleNodeRejected):
        node.prepare()


def test_core_execution_marker_loss_at_native_boundary_stops_write_and_preserves_unknown(node):
    node.prepare()
    node.request_hook = lambda *_args: setattr(node, "marker", False)
    result = node.execute()
    assert result.receipt.outcome == "unknown" and result.receipt.effect_possible
    assert node.effects == ["spawn"] and node.native_calls == []
    node.request_hook = None; node.marker = True
    again = node.execute()
    assert again.receipt.outcome == "unknown" and node.effects == ["spawn"] and node.native_calls == []


def test_transport_lease_expiry_during_core_authority_wait_prevents_driver_entry(node):
    node.prepare()
    def expire(stage):
        if stage == "execute":
            node.driver_time.now += timedelta(seconds=3); node.monotonic[0] += 3
    node.core_hook = expire
    result = node.execute()
    assert result.receipt.outcome == "definitively_not_started" and not result.receipt.effect_possible
    assert node.effects == [] and node.native_calls == []


def test_no_protocol_response_cannot_manufacture_lifecycle_ack_from_success_return(node):
    node.prepare()
    def fabricated(operation):
        return node.driver._run(operation, "spawn", {"profile": node.driver.profile.binding()},
            lambda: {"receipt_layer": "runtime_acknowledged", "ownership": "exclusive_owned",
                "binding_id": node.driver.binding_id, "binding": asdict(node.driver.identity),
                "thread_id": "thread_made_up", "session_id": "provider_made_up", "native_session_id": "ses_made_up"})
    node.driver.spawn = fabricated
    result = node.execute()
    assert result.receipt.outcome == "unknown" and result.receipt.native_session_ref is None
    assert node.effects == [] and node.native_calls == []


def test_private_journal_is_never_read_before_current_original_scope_authority(node, monkeypatch):
    node.prepare(); node.execute(); node.read_allowed = False
    monkeypatch.setattr(node.controller, "_record", lambda *_args: pytest.fail("denied read opened private history"))
    with pytest.raises(PermissionError):
        node.reconcile()


@pytest.mark.parametrize("damage", ["missing", "corrupt_input"])
def test_damaged_original_history_remains_unknown_without_driver_reentry(node, damage):
    node.prepare(); node.execute()
    before = len(node.native_calls)
    if damage == "missing":
        Path(node.driver.journal.path).unlink()
    else:
        with node.driver.journal._connect() as connection:
            connection.execute("UPDATE driver_operations SET input_hash='corrupt' WHERE operation_id=?",
                (node.permit.permit.plan.driver_operation_id,))
    result = node.reconcile()
    assert result.receipt.outcome == "unknown" and result.receipt.reason_code == "lifecycle_original_journal_unavailable"
    assert node.effects == ["spawn"] and len(node.native_calls) == before


def test_original_positive_ack_does_not_depend_on_current_profile_or_account_selection(node):
    node.prepare(); first = node.execute()
    node.capacity.account = "9" * 64; node.driver.profile.environment["new-current-selection"] = "changed"
    before = len(node.native_calls)
    result = node.reconcile()
    assert result.receipt.outcome == "acknowledged" and result.receipt.provider_generation == first.receipt.provider_generation
    assert len(node.native_calls) == before and node.effects == ["spawn"]


def test_reconstructed_driver_reads_retained_original_ack_without_launch_profile_or_native_reattachment(node):
    node.prepare()
    original = node.execute()
    assert original.receipt.outcome == "acknowledged"
    old = node.driver
    node.controller.close()
    old.journal.release_claim(old._claim_token)  # Simulate loss of the old process-local owner.
    current = type(old)(old.binding_id, old.profile, old.journal, identity=old.identity,
        check_current=lambda *_args: pytest.fail("historical ACK read entered ordinary Native authority"),
        supervisor=old.supervisor, clock=node.clock)
    recovered = ReceiverLifecycleNode(current, node.config, node.node_key, clock=node.clock,
        resolve_original=node.resolve, require_current_execution=node.require, resolve_original_read=node.read)
    before = len(node.native_calls)
    try:
        result = recovered.reconcile(node.permit, challenge=node.challenge, observation=node.observation)
        assert result.receipt.outcome == "acknowledged"
        assert result.receipt.native_session_ref == original.receipt.native_session_ref
        assert current.owned is current.client is None and current.ownership == "unbound"
        assert len(node.native_calls) == before and node.effects == ["spawn"]
    finally:
        recovered.close()
        old.journal.release_claim(current._claim_token)


def test_missing_original_spawn_rows_after_native_effect_never_attest_absence_or_contact_native_again(node):
    node.prepare()
    assert node.execute().receipt.outcome == "acknowledged"
    reference = node.permit.permit.plan.driver_operation_id
    with node.driver.journal._connect() as connection:
        connection.execute("DELETE FROM driver_events WHERE operation_id=?", (reference,))
        connection.execute("DELETE FROM driver_operations WHERE operation_id=?", (reference,))
    before = len(node.native_calls)
    result = node.execute()
    assert result.receipt.outcome == "unknown" and result.receipt.effect_possible
    assert node.effects == ["spawn"] and len(node.native_calls) == before


def test_new_process_requires_original_source_process_birth_before_native_protocol(node):
    node.prepare(); node.process_record_birth = "another-source-child"
    result = node.execute()
    assert result.receipt.outcome == "unknown" and node.effects == ["spawn"] and node.native_calls == []


def test_message_less_read_lease_rejects_callback_time_native_client_replacement(node):
    node.start_existing()
    replaced = False
    def replace_client(_method, _params):
        nonlocal replaced
        if not replaced:
            replaced = True
            node.driver.client = SimpleNamespace(endpoint="foreign-client", request=lambda *_args, **_kwargs: pytest.fail("foreign Native read"))
    node.request_hook = replace_client
    challenge = LifecycleChallenge(source=node.source, target=node.snapshot.target(), authority_key_id=node.config.authority_key_id,
        authority_key_revision=node.config.authority_key_revision, request_id="owner-race", nonce="9" * 64,
        issued_at=node.driver_time.now, deadline=node.driver_time.now + timedelta(seconds=10))
    observed = node.controller.observe(sign_challenge(challenge, node.key))
    assert observed.observation.capacity.state == "unknown" and replaced and node.native_calls == []


def test_close_does_not_revive_mutation_capabilities_through_permissive_legacy_fallback(node):
    node.prepare(); node.execute()
    operation = node.capabilities[0]
    node.controller.close()
    with pytest.raises(DriverRejected):
        node.driver._run(operation, "spawn", {"profile": node.driver.profile.binding()},
            lambda: pytest.fail("retired lifecycle capability reached Driver action"))
    ordinary = AuthorizedOperation("ordinary-after-close", "command", "message", "grant", None)
    node.driver.check_current(ordinary, node.driver.identity)
    assert node.core_calls[-1][0] == "ordinary"


def test_driver_callback_replacement_invalidates_controller_before_effect(node):
    node.prepare()
    node.driver.check_current = node.controller._original_check
    with pytest.raises(DriverRejected):
        node.execute()
    assert node.effects == [] and node.native_calls == []


def test_post_effect_read_authority_loss_returns_unknown_then_original_ack_under_fresh_read(node):
    node.prepare()
    node.request_hook = lambda *_args: setattr(node, "read_allowed", False)
    result = node.execute()
    assert result.receipt.outcome == "unknown" and result.receipt.effect_possible and result.receipt.native_session_ref is None
    assert node.effects == ["spawn"]
    before = len(node.native_calls)
    node.read_allowed = True; node.request_hook = None
    result = node.reconcile()
    assert result.receipt.outcome == "acknowledged" and len(node.native_calls) == before and node.effects == ["spawn"]


def test_core_and_native_callbacks_hold_no_driver_sqlite_transaction(node):
    checks = []
    def exclusive(*_args):
        connection = sqlite3.connect(node.driver.journal.path, timeout=0, isolation_level=None)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("ROLLBACK")
            checks.append(True)
        finally:
            connection.close()
    node.core_hook = exclusive
    node.request_hook = exclusive
    node.prepare(); result = node.execute()
    assert result.receipt.outcome == "acknowledged" and checks and node.effects == ["spawn"]


def test_node_signer_must_match_actual_installed_endpoint_key(node):
    with pytest.raises(LifecycleNodeRejected, match="Node lifecycle") as failure:
        ReceiverLifecycleNode(node.driver, node.config, SigningKey.generate(), clock=node.clock,
            resolve_original=node.resolve, require_current_execution=node.require, resolve_original_read=node.read)
    assert failure.value.code == "lifecycle_installed_node_key_mismatch" and node.effects == [] and node.native_calls == []


def test_observation_expiring_during_last_core_authorization_cannot_be_published(node):
    node.prepare()
    total, calls = len(node.core_calls), 0
    expiry = (node.observation.observation.capacity.valid_until - node.observation.observation.capacity.observed_at).total_seconds() + 1
    def expire_on_last_callback(_stage):
        nonlocal calls
        calls += 1
        if calls == total:
            node.driver_time.now += timedelta(seconds=expiry); node.monotonic[0] += expiry
    node.core_hook = expire_on_last_callback
    with pytest.raises(ValueError):
        node.prepare()
    assert calls == total and node.effects == [] and node.native_calls == []


def test_revocation_during_local_profile_capture_is_checked_before_observation_publication(node, monkeypatch):
    kind = type(node.driver.profile)
    actual = kind.validate

    def revoked(profile):
        actual(profile)
        node.core_allowed = False

    monkeypatch.setattr(kind, "validate", revoked)
    with pytest.raises(PermissionError):
        node.prepare()
    assert node.effects == [] and node.native_calls == []


@pytest.mark.parametrize("identity", ["driver_binding_id", "configured_capacity_id"])
def test_valid_signed_foreign_driver_capacity_cannot_read_or_attest_this_journal(node, identity):
    node.prepare()
    observed = node.observation.observation
    update = {"driver_binding_id": "another-driver-binding"} if identity == "driver_binding_id" else {
        "binding": replace(observed.capacity.binding, attempt_id="another-configured-capacity")}
    changed = observed.model_copy(update={"capacity": observed.capacity.model_copy(update=update)})
    node.observation = sign_observation(changed, node.node_key)
    plan = build_lifecycle_plan(node.challenge.challenge, changed, "spawn")
    permit = node.permit.permit.model_copy(update={"plan": plan, "semantic_digest": lifecycle_plan_digest(plan),
        "observation_digest": sha256(changed)})
    node.permit = sign_permit(permit, node.key)
    with pytest.raises(LifecycleNodeRejected) as failure:
        node.reconcile()
    assert failure.value.code == "lifecycle_original_driver_capacity_changed"
    assert node.effects == [] and node.native_calls == [] and node.read_calls == []


def test_corrupted_actual_native_ack_session_identity_remains_unknown(node):
    node.prepare(); original = node.execute()
    assert original.receipt.outcome == "acknowledged"
    operation_id = node.permit.permit.plan.driver_operation_id
    with node.driver.journal._connect() as connection:
        row = connection.execute("SELECT result_json FROM driver_operations WHERE operation_id=?", (operation_id,)).fetchone()
        result = json.loads(row[0])
        if isinstance(node.driver, CodexAppServerDriver):
            result["session_id"] = None
            for sequence, body in connection.execute("SELECT sequence,body FROM driver_events WHERE operation_id=? AND kind='rpc_response'",
                                                    (operation_id,)).fetchall():
                value = json.loads(body)
                if type(value.get("result", {}).get("thread")) is dict:
                    value["result"]["thread"]["sessionId"] = None
                    connection.execute("UPDATE driver_events SET body=? WHERE sequence=?", (json.dumps(value), sequence))
        else:
            result["native_session_id"] = "ses_another_wellformed"
        connection.execute("UPDATE driver_operations SET result_json=? WHERE operation_id=?", (json.dumps(result), operation_id))
    before = len(node.native_calls)
    receipt = node.reconcile().receipt
    assert receipt.outcome == "unknown" and receipt.native_session_ref is None and len(node.native_calls) == before


def test_exclusive_ownership_loss_before_native_send_blocks_original_session_effect(node):
    node.prepare()
    node.request_hook = lambda *_args: setattr(node.driver, "ownership", "attached_read_only")
    result = node.execute()
    assert result.receipt.outcome == "unknown" and result.receipt.effect_possible
    assert node.effects == ["spawn"] and node.native_calls == [] and result.receipt.native_session_ref is None


def test_legacy_opencode_creation_record_without_actual_response_identity_stays_unknown(node):
    if isinstance(node.driver, CodexAppServerDriver):
        pytest.skip("OpenCode http_response-specific journal history")
    node.prepare(); first = node.execute()
    assert first.receipt.outcome == "acknowledged"
    operation_id = node.permit.permit.plan.driver_operation_id
    with node.driver.journal._connect() as connection:
        for sequence, raw in connection.execute("SELECT sequence,body FROM driver_events WHERE operation_id=? AND kind='http_response'",
                                                (operation_id,)).fetchall():
            body = json.loads(raw); body.pop("native_session_id", None)
            connection.execute("UPDATE driver_events SET body=? WHERE sequence=?", (json.dumps(body), sequence))
    before = len(node.native_calls)
    receipt = node.reconcile().receipt
    assert receipt.outcome == "unknown" and receipt.effect_possible and receipt.native_session_ref is None
    assert len(node.native_calls) == before

"""Actual private SQLite/kernel claims with controlled read-only capacity evidence.

No process, socket, Native Host/model or PostgreSQL is contacted. Process and
Native observations are explicit doubles, not qualification evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import BindingIdentity, CodexAppServerDriver, DriverJournal, LaunchProfile
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.receiver_contract import native_generation
from runtime.receiver_lifecycle import AuthorizedLifecycleOperation, lifecycle_operation_id
from runtime.receiver_lifecycle_capacity import (
    CapacityEvidenceUnavailable,
    capture_capacity_profile,
    create_capacity_reservation,
    observe_receiver_capacity,
)
from runtime.receiver_lifecycle_contract import capacity_semantic_digest
from runtime.supervisor import OwnedProcess

BINDING = BindingIdentity("node", "boot", "runtime", "actual-configured-capacity", "slot", 3)
PRIVATE = "PRIVATE_SELECTED_ACCOUNT_ENVIRONMENT"


class Clock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def observation_time(self):
        return self.now


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows stat derives execute bits from the filename")
def test_windows_executable_profile_identity_accepts_path_handle_mode_difference_but_detects_mutation(tmp_path):
    from runtime.receiver_lifecycle_capacity import _file, _stamps_current

    executable = tmp_path/"profile.exe"
    executable.write_bytes(b"actual file metadata, no process execution")
    evidence, stamp = _file(executable, 4096)
    assert evidence["sha256"] == file_hash(executable)
    _stamps_current({str(executable): stamp})
    try:
        executable.chmod(0o444)
        with pytest.raises(CapacityEvidenceUnavailable) as caught:
            _stamps_current({str(executable): stamp})
        assert caught.value.reason_code == "profile_file_changed_after_readback"
    finally:
        executable.chmod(0o666)


@contextmanager
def configured_capacity(harness, tmp_path, *, binding=BINDING):
    executable, schema = tmp_path / "controlled-executable", tmp_path / "controlled-schema.json"
    executable.write_bytes(b"actual-private-fixture-bytes")
    schema.write_text("{}", encoding="utf-8")
    environment = {"PATH": "actual-selected-path", "ACCOUNT_VALUE": PRIVATE}
    if harness == "codex":
        home = tmp_path / "codex-home"; home.mkdir()
        config = home / "config.toml"; config.write_text('approval_policy="never"\n', encoding="utf-8")
        profile = LaunchProfile(str(executable), file_hash(executable), "controlled-native", str(schema), file_hash(schema),
            str(tmp_path), str(home), file_hash(config), "actual-profile", environment, execution_mode="native")
        kind = CodexAppServerDriver
    else:
        roots = {name: tmp_path / name for name in ("home", "config", "data", "state", "cache", "temp")}
        for path in roots.values():
            path.mkdir()
        config = roots["config"] / "opencode" / "opencode.json"; config.parent.mkdir(); config.write_text("{}", encoding="utf-8")
        profile = OpenCodeLaunchProfile(str(executable), file_hash(executable), "controlled-native", str(schema), file_hash(schema),
            str(tmp_path), *(str(roots[name]) for name in ("home", "config", "data", "state", "cache", "temp")),
            file_hash(config), None, None, None, environment, execution_mode="native")
        kind = OpenCodeNativeDriver
    namespace_allowed, namespace_calls = [True], []

    def authorize_namespace(namespace, binding_id, actual_binding):
        assert namespace.parent == tmp_path and binding_id == "actual-driver-binding" and actual_binding == binding
        namespace_calls.append(namespace)
        if not namespace_allowed[0]:
            raise PermissionError("private namespace no longer authorized")

    reservation = create_capacity_reservation(tmp_path / "new-private-capacity", binding_id="actual-driver-binding",
        binding=binding, authorize_current_namespace=authorize_namespace)
    journal = DriverJournal(reservation.journal_path)
    journal.adopt_lifecycle_schema()
    driver = kind("actual-driver-binding", profile, journal, identity=binding,
                  check_current=lambda *_args: pytest.fail("builder manufactured a Driver operation"))
    clock = Clock(); driver.clock = clock
    state = SimpleNamespace(driver=driver, journal=journal, config=config, executable=executable, schema=schema,
        allowed=True, calls=[], account="1" * 64, input_state="ready", blocker="none", native_hook=None, supervisor_hook=None, authorize_hook=None,
        proof={"verified": True, "root_exited": False, "root_pid": 49152, "pid": 49152, "birth_ref": "actual-controlled-birth", "containment_id": "actual-controlled-job"})
    state.reservation, state.namespace_allowed, state.namespace_calls = reservation, namespace_allowed, namespace_calls
    state.authorize_namespace = authorize_namespace

    def authorize(actual):
        assert actual is driver
        state.calls.append("authorize")
        if state.authorize_hook:
            state.authorize_hook()
        if not state.allowed:
            raise PermissionError("PRIVATE_NODE_AUTHORIZATION_FAILURE")

    def account(actual):
        assert actual is driver
        state.calls.append("account")
        return state.account

    def inspect(owned):
        assert owned is driver.owned
        state.calls.append("supervisor")
        if state.supervisor_hook:
            state.supervisor_hook()
        return dict(state.proof)

    def native(actual):
        assert actual is driver and state.calls[-1] == "authorize"
        state.calls.append("native")
        evidence = "native-input-observation:" + "2" * 64
        now = clock.now
        axes = {axis: {"knowledge": "observed", "value": value, "reason_code": None, "evidence_ref": evidence} for axis, value in
                (("connection", "connected"), ("process", "present"), ("session", "present"), ("input", state.input_state), ("blocker", state.blocker))}
        value = {"binding_id": driver.binding_id, "native_session_ref": driver.thread_id if harness == "codex" else driver.session_id,
            "ownership": "exclusive_owned", "dedicated_input": True, "schema_verified": True, "source": "native_api", "evidence_ref": evidence,
            "protocol_digest": "3" * 64, "config_digest": "4" * 64, "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=2)).isoformat(),
            "axes": axes, "private_pending_body": PRIVATE}
        if state.native_hook:
            state.native_hook(value)
        return value

    driver.supervisor = SimpleNamespace(inspect=inspect)
    for method in ("spawn", "resume", "invoke", "terminate"):
        setattr(driver, method, lambda *_args, **_kwargs: pytest.fail("capacity getter attempted a Driver mutation"))
    state.authorize, state.account_reader, state.native = authorize, account, native
    state.witness = capture_capacity_profile(driver, authorize_current=authorize, account_fingerprint=account)
    state.observe = lambda **options: observe_receiver_capacity(driver, authorize_current=authorize,
        profile_witness=options.pop("profile_witness", state.witness), reservation_witness=options.pop("reservation_witness", reservation),
        native_readback=options.pop("native_readback", native), **options)
    try:
        yield state
    finally:
        journal.release_claim(driver._claim_token)


@pytest.fixture(params=("codex", "opencode"))
def capacity(request, tmp_path):
    with configured_capacity(request.param, tmp_path) as state:
        yield state


def existing(state, *, uncertain=False):
    driver, journal = state.driver, state.journal
    driver.owned = OwnedProcess(SimpleNamespace(pid=49152), "actual-controlled-job", "actual-controlled-birth")
    driver.client = object(); driver.ownership = "exclusive_owned"
    if isinstance(driver, CodexAppServerDriver):
        driver.thread_id, driver.session_id = "actual-thread", "actual-provider-session"
    else:
        driver.session_id = "actual-opencode-session"
    op = AuthorizedLifecycleOperation(lifecycle_operation_id("actual-node-capacity-creation", "spawn"), "actual-node-command",
        "actual-node-capacity-creation", "actual-node-grant", None, "spawn", driver.binding_id, driver.identity)
    journal.begin(op, driver.binding_id, "spawn", {"binding": asdict(driver.identity), "profile": driver.profile.binding()})
    journal.event(op.operation_id, "process_dispatch", {"binding": asdict(driver.identity), "profile": driver.profile.binding()})
    journal.event(op.operation_id, "process_started", {"pid": 49152, "birth_ref": "actual-controlled-birth", "containment_id": "actual-controlled-job"})
    journal.finish(op.operation_id, "uncertain" if uncertain else "acknowledged", {"controlled_receipt": True})
    return op


def snapshot(state):
    with sqlite3.connect(state.journal.path) as connection:
        return tuple(connection.execute("SELECT * FROM " + table).fetchall() for table in ("driver_operations", "driver_events", "driver_journal_metadata"))


def test_fresh_requires_actual_reserved_claim_profile_account_and_intact_empty_history(capacity):
    before = snapshot(capacity)
    fact = capacity.observe()
    assert fact.state == "fresh" and fact.ownership == "exclusive_reserved" and fact.journal_state == "clear"
    assert fact.input_state == "not_started" and fact.blocker == "none"
    assert fact.process is None and fact.native_session_ref is None and fact.provider_generation is None
    assert fact.absence_evidence_ref and fact.kernel_claim_ref and fact.profile_evidence_ref
    assert fact.profile_fingerprint == capacity.witness.fingerprint
    assert snapshot(capacity) == before and "native" not in capacity.calls and "supervisor" not in capacity.calls
    assert PRIVATE not in fact.model_dump_json()


def test_longer_private_reservation_window_never_extends_existing_native_input_evidence(capacity):
    fresh = capacity.observe(fresh_ttl_seconds=15)
    assert fresh.state == "fresh" and (fresh.valid_until - fresh.observed_at).total_seconds() == 15
    existing(capacity)
    bound = capacity.observe(fresh_ttl_seconds=15)
    assert bound.state == "existing" and (bound.valid_until - bound.observed_at).total_seconds() <= 2


@pytest.mark.parametrize("lifetime", [0, 31, True, "15"])
def test_private_reservation_window_cannot_exceed_contract_or_choose_an_untyped_lifetime(capacity, lifetime):
    with pytest.raises(ValueError):
        capacity.observe(fresh_ttl_seconds=lifetime)


def test_fresh_is_unknown_without_preconstructor_private_namespace_creation(capacity):
    fact = capacity.observe(reservation_witness=None)
    assert fact.state == "unknown" and fact.reason_code == "fresh_capacity_provenance_missing"
    assert fact.absence_evidence_ref is None and "native" not in capacity.calls


def test_provisioning_never_reuses_an_existing_namespace_even_after_journal_loss(capacity):
    from pathlib import Path
    path = Path(capacity.journal.path)
    path.unlink()
    with pytest.raises(FileExistsError):
        create_capacity_reservation(path.parent, binding_id=capacity.driver.binding_id,
            binding=BINDING, authorize_current_namespace=capacity.authorize_namespace)
    assert not path.exists() and capacity.observe().state == "unknown"


def test_preconstructor_witness_refuses_original_journal_deleted_and_recreated_before_profile_capture(capacity):
    from pathlib import Path
    path = Path(capacity.journal.path)
    path.rename(path.with_name("lost-original.sqlite"))
    replacement = DriverJournal(path)
    replacement.adopt_lifecycle_schema()
    # Even a newly captured valid profile cannot re-qualify this old namespace.
    capacity.witness = capture_capacity_profile(capacity.driver, authorize_current=capacity.authorize,
        account_fingerprint=capacity.account_reader)
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.reason_code == "fresh_capacity_namespace_identity_changed"
    assert fact.absence_evidence_ref is None and "native" not in capacity.calls


def test_namespace_current_enrollment_authorization_is_required_again_for_fresh(capacity):
    capacity.namespace_allowed[0] = False
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.reason_code == "capacity_authorization_denied"
    assert fact.evidence_refs == () and fact.profile_fingerprint is None and fact.absence_evidence_ref is None


def test_profile_baseline_cannot_be_reconstructed_after_a_child_has_been_started(capacity):
    existing(capacity)
    with pytest.raises(CapacityEvidenceUnavailable, match="Node capacity evidence is unavailable") as failure:
        capture_capacity_profile(capacity.driver, authorize_current=capacity.authorize, account_fingerprint=capacity.account_reader)
    assert failure.value.reason_code == "profile_baseline_requires_pre_effect_capacity"
    assert capacity.observe().state == "existing"  # Original pre-effect capture remains valid.


def test_provisioning_denial_occurs_before_creating_a_namespace(capacity):
    from pathlib import Path
    namespace = Path(capacity.journal.path).parent.parent / "unauthorized-new-capacity"
    capacity.namespace_allowed[0] = False
    with pytest.raises(CapacityEvidenceUnavailable) as failure:
        create_capacity_reservation(namespace, binding_id=capacity.driver.binding_id, binding=BINDING,
            authorize_current_namespace=capacity.authorize_namespace)
    assert failure.value.reason_code == "capacity_authorization_denied" and not namespace.exists()


def test_missing_actual_kernel_claim_never_yields_fresh_or_existing(capacity):
    existing(capacity)
    capacity.journal.release_claim(capacity.driver._claim_token)
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.kernel_claim_ref is None and fact.process is None
    assert "native" not in capacity.calls and "supervisor" not in capacity.calls


@pytest.mark.parametrize("unresolved", [False, True])
def test_existing_owned_process_session_and_generation_keep_journal_blocker_separate(capacity, unresolved):
    existing(capacity, uncertain=unresolved)
    before = snapshot(capacity)
    fact = capacity.observe()
    assert fact.state == "existing" and fact.ownership == "exclusive_owned"
    assert fact.journal_state == ("unresolved" if unresolved else "clear")
    assert fact.process.pid == 49152 and fact.process.birth_ref == "actual-controlled-birth"
    assert fact.provider_generation == native_generation(capacity.driver.binding_id, asdict(BINDING), fact.native_session_ref)
    assert fact.input_state == "ready" and fact.blocker == "none" and fact.absence_evidence_ref is None
    assert snapshot(capacity) == before and capacity.calls.count("native") == 1
    assert PRIVATE not in fact.model_dump_json()


@pytest.mark.parametrize("input_state,blocker", [("busy", "none"), ("busy", "approval"), ("busy", "question"), ("ready", "draft")])
def test_existing_busy_and_blocked_are_observed_without_becoming_a_resume_permission(capacity, input_state, blocker):
    existing(capacity); capacity.input_state, capacity.blocker = input_state, blocker
    fact = capacity.observe()
    assert fact.state == "existing" and fact.input_state == input_state and fact.blocker == blocker


def test_authorization_denial_happens_before_journal_native_or_supervisor_reads(capacity, monkeypatch):
    existing(capacity)
    capacity.allowed = False
    monkeypatch.setattr(capacity.driver.supervisor, "inspect", lambda *_args: pytest.fail("denied process read"))
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.process is None and fact.native_session_ref is None
    assert "native" not in capacity.calls and PRIVATE not in fact.model_dump_json()


@pytest.mark.parametrize("evidence", ["missing_db", "missing_table", "corrupt_input", "orphan_effect", "corrupt_event"])
def test_missing_or_corrupt_history_is_unknown_and_never_recreated(capacity, evidence):
    if evidence == "missing_db":
        from pathlib import Path
        Path(capacity.journal.path).unlink()
    else:
        if evidence == "corrupt_input":
            existing(capacity)
        with sqlite3.connect(capacity.journal.path) as connection:
            if evidence == "missing_table":
                connection.execute("DROP TABLE driver_events")
            elif evidence == "corrupt_input":
                connection.execute("UPDATE driver_operations SET input_hash=?", ("0" * 64,))
            elif evidence == "orphan_effect":
                connection.execute("INSERT INTO driver_events(operation_id,kind,body,observed_at) VALUES('missing','process_dispatch','{}',?)", (datetime.now(UTC).isoformat(),))
            else:
                connection.execute("INSERT INTO driver_events(operation_id,kind,body,observed_at) VALUES('read','rpc_response','not-json',?)", (datetime.now(UTC).isoformat(),))
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.absence_evidence_ref is None
    if evidence == "missing_db":
        from pathlib import Path
        assert not Path(capacity.journal.path).exists()
    assert "native" not in capacity.calls


def test_prior_possible_effect_cannot_become_fresh_after_handles_disappear(capacity):
    existing(capacity)
    capacity.driver.owned = capacity.driver.client = capacity.driver.session_id = None
    if isinstance(capacity.driver, CodexAppServerDriver):
        capacity.driver.thread_id = None
    capacity.driver.ownership = "unbound"
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.absence_evidence_ref is None and "native" not in capacity.calls


@pytest.mark.parametrize("change", ["birth", "containment", "unverified", "exited", "pid"])
def test_existing_process_needs_exact_actual_supervisor_proof(capacity, change):
    existing(capacity)
    capacity.proof.update({"birth_ref": "different"} if change == "birth" else {"containment_id": "different"} if change == "containment" else
                          {"verified": False} if change == "unverified" else {"root_exited": True} if change == "exited" else {"root_pid": 100})
    assert capacity.observe().state == "unknown" and "native" not in capacity.calls


def test_existing_requires_recorded_process_birth_for_the_same_binding_profile(capacity):
    existing(capacity)
    with sqlite3.connect(capacity.journal.path) as connection:
        connection.execute("UPDATE driver_events SET body=? WHERE kind='process_started'",
            (json.dumps({"pid": 49152, "birth_ref": "different-original-child", "containment_id": "actual-controlled-job"}),))
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.process is not None and "native" not in capacity.calls


@pytest.mark.parametrize("damage", ["deleted_events", "unknown_state", "corrupt_result", "replaced_file"])
def test_complete_original_journal_identity_and_history_are_required(capacity, damage):
    existing(capacity)
    if damage == "replaced_file":
        from pathlib import Path
        path = Path(capacity.journal.path)
        path.rename(path.with_name("original-preserved.sqlite"))
        DriverJournal(path)
    else:
        with sqlite3.connect(capacity.journal.path) as connection:
            if damage == "deleted_events":
                connection.execute("DELETE FROM driver_events")
                connection.execute("DELETE FROM driver_operations")
                capacity.driver.owned = capacity.driver.client = capacity.driver.session_id = None
                if isinstance(capacity.driver, CodexAppServerDriver):
                    capacity.driver.thread_id = None
                capacity.driver.ownership = "unbound"
            elif damage == "unknown_state":
                connection.execute("UPDATE driver_operations SET state='invented-clear'")
            else:
                connection.execute("UPDATE driver_operations SET result_json='[]'")
    fact = capacity.observe()
    assert fact.state == "unknown" and fact.absence_evidence_ref is None and "native" not in capacity.calls


def test_authorization_loss_at_final_publication_clears_previously_read_private_facts(capacity):
    existing(capacity)
    count = 0

    def revoke_at_final_guard():
        nonlocal count
        if "native" in capacity.calls:
            count += 1
            if count == 4:
                capacity.allowed = False

    capacity.authorize_hook = revoke_at_final_guard
    fact = capacity.observe()
    assert capacity.calls.count("native") == 1 and count == 4
    assert fact.state == "unknown" and fact.reason_code == "capacity_authorization_denied"
    assert fact.process is None and fact.native_session_ref is None and fact.provider_generation is None
    assert fact.profile_fingerprint is None and fact.evidence_refs == () and fact.journal_state == "unknown"


@pytest.mark.parametrize("change", ["missing_profile", "account", "environment", "config", "executable", "schema"])
def test_profile_account_environment_and_actual_bytes_match_node_capture(capacity, change):
    if change == "account":
        capacity.account = "9" * 64
    elif change == "environment":
        capacity.driver.profile.environment["ACCOUNT_VALUE"] = "DIFFERENT_PRIVATE_VALUE"
    elif change in {"config", "executable", "schema"}:
        getattr(capacity, change).write_bytes(b"changed-current-file")
    fact = capacity.observe(profile_witness=None if change == "missing_profile" else capacity.witness)
    assert fact.state == "unknown" and fact.absence_evidence_ref is None and "native" not in capacity.calls
    assert PRIVATE not in fact.model_dump_json() and "DIFFERENT_PRIVATE" not in fact.model_dump_json()


def test_account_witness_is_explicit_node_callback_not_a_guessed_secret_file(capacity):
    with pytest.raises(CapacityEvidenceUnavailable):
        capture_capacity_profile(capacity.driver, authorize_current=capacity.authorize, account_fingerprint=None)
    assert capacity.observe(profile_witness=None).state == "unknown"


@pytest.mark.parametrize("change", ["session", "generation_scope", "binding", "auth", "profile", "account", "expired", "journal_effect", "supervisor"])
def test_changes_during_actual_readback_invalidate_existing_without_mutation(capacity, change):
    existing(capacity)

    def changed(value):
        if change == "session":
            capacity.driver.session_id = "different-session"
        elif change == "generation_scope":
            value["native_session_ref"] = "different-session"
        elif change == "binding":
            capacity.driver.identity = replace(BINDING, revision=4)
        elif change == "auth":
            capacity.allowed = False
        elif change == "profile":
            capacity.driver.profile.environment["NEW_SELECTION"] = "changed"
        elif change == "account":
            capacity.account = "9" * 64
        elif change == "expired":
            capacity.driver.clock.now += timedelta(seconds=3)
        elif change == "supervisor":
            capacity.driver.supervisor = SimpleNamespace(inspect=lambda _owned: dict(capacity.proof))
        else:
            capacity.journal.event("new-orphan", "rpc_dispatch", {"method": "turn/start"})
    capacity.native_hook = changed
    fact = capacity.observe()
    assert fact.state == "unknown" and capacity.calls.count("native") == 1 and fact.absence_evidence_ref is None


@pytest.mark.parametrize("change", ["binding", "process", "schema", "dedicated", "axis", "input_evidence"])
def test_native_readback_scope_and_positive_axes_are_verified(capacity, change):
    existing(capacity)
    def changed(value):
        if change == "binding":
            value["binding_id"] = "foreign-binding"
        elif change == "process":
            value["axes"]["process"]["knowledge"] = "inferred"
        elif change == "schema":
            value["schema_verified"] = False
        elif change == "dedicated":
            value["dedicated_input"] = False
        elif change == "axis":
            value["axes"]["session"]["evidence_ref"] = "foreign-evidence"
        else:
            value["axes"]["input"]["evidence_ref"] = "foreign-evidence"
    capacity.native_hook = changed
    fact = capacity.observe()
    if change == "input_evidence":
        assert fact.state == "existing" and fact.input_state == "unknown"
    else:
        assert fact.state == "unknown"


def test_attached_or_unproven_ownership_never_becomes_existing_or_fresh(capacity):
    existing(capacity); capacity.driver.ownership = "shared_attached"
    fact = capacity.observe()
    assert fact.state == "unknown" and "native" not in capacity.calls


def test_readonly_observer_never_uses_create_capable_journal_connection(capacity, monkeypatch):
    existing(capacity)
    monkeypatch.setattr(capacity.journal, "_connect", lambda: pytest.fail("getter opened a create-capable SQLite connection"))
    assert capacity.observe().state == "existing"


def test_readonly_journal_events_do_not_invalidate_actual_existing_capacity(capacity):
    existing(capacity)
    def observed(_value):
        capacity.journal.event("message-less-capacity-read", "rpc_intent", {"method": "thread/read"})
        capacity.journal.event("message-less-capacity-read", "rpc_response", {"result": {"private": PRIVATE}})
    capacity.native_hook = observed
    assert capacity.observe().state == "existing"


def test_observation_renewal_preserves_semantic_capacity_digest(capacity):
    existing(capacity)
    first = capacity.observe()
    capacity.driver.clock.now += timedelta(milliseconds=100)
    second = capacity.observe()
    assert first.observed_at != second.observed_at and capacity_semantic_digest(first) == capacity_semantic_digest(second)

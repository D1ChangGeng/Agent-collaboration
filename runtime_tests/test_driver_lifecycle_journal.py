"""Explicit actual SQLite adoption and pure Driver lifecycle boundaries.

No process/socket/Host/model is started. Controlled _run callbacks exercise
Driver state/journal semantics only; their receipts are not Native qualification.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    DriverRejected,
    OutcomeUncertain,
)
from runtime.communication_tools import NATIVE_COLLABORATION_TOOLS
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.receiver_contract import native_generation
from runtime.receiver_lifecycle import AuthorizedLifecycleOperation, lifecycle_operation_id

DEADLINE = datetime(2050, 1, 1, tzinfo=UTC)
BINDING = BindingIdentity("node", "boot", "runtime", "actual-configured-capacity", "slot", 3)


def legacy(identifier="old", *, deadline=DEADLINE):
    return AuthorizedOperation(identifier, "command-" + identifier, "message-" + identifier, "actual-grant", deadline)


def lifecycle(source="recovery-one", *, action="spawn", binding=BINDING, **changes):
    session = "controlled-existing-session" if action == "resume" else None
    values = {"operation_id": lifecycle_operation_id(source, action), "command_id": "command-" + source,
        "source_ref": source, "grant_ref": "actual-original-grant", "deadline": DEADLINE, "action": action,
        "binding_id": "driver-binding", "binding": binding, "native_session_ref": session,
        "provider_generation": native_generation("driver-binding", asdict(binding), session) if session else None}
    return AuthorizedLifecycleOperation(**(values | changes))


def begin(journal, operation, *, payload=None):
    return journal.begin(operation, "driver-binding", operation.action,
                         {"binding": asdict(operation.binding)} | (payload or {}))


def snapshot(journal):
    with sqlite3.connect(journal.path) as connection:
        return (connection.execute("SELECT operation_id,binding_id,command_id,message_id,action,input_hash,input_json,state,result_json "
            "FROM driver_operations ORDER BY operation_id").fetchall(),
            connection.execute("SELECT * FROM driver_events ORDER BY sequence").fetchall(),
            connection.execute("SELECT * FROM sqlite_sequence ORDER BY name").fetchall())


def columns(journal):
    with sqlite3.connect(journal.path) as connection:
        return {row[1]: row for row in connection.execute("PRAGMA table_info(driver_operations)")}


def test_default_open_preserves_legacy_schema_and_requires_explicit_adoption(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    assert columns(journal)["message_id"][3] == 1 and "source_kind" not in columns(journal)
    with pytest.raises(DriverRejected, match="explicit lifecycle"):
        begin(journal, lifecycle())
    reopened = DriverJournal(journal.path)
    assert reopened.preview_lifecycle_adoption()["schema_version"] == 1
    assert "source_ref" not in columns(reopened) and snapshot(reopened)[0] == []


def test_explicit_adoption_preserves_every_legacy_byte_hash_result_event_and_sequence(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    operation = legacy()
    journal.begin(operation, "driver-binding", "invoke", {"text": "原文 😀", "actual": [1, 2]})
    result = {"operation_id": "old", "message_id": "message-old", "native_ack_ref": "controlled-old-proof"}
    journal.event("old", "rpc_dispatch", {"method": "turn/start", "body": "原文 😀"})
    journal.finish("old", "acknowledged", result)
    before, original = snapshot(journal), journal.read("old")
    preview = journal.preview_lifecycle_adoption()
    assert "source_kind" not in columns(journal)  # Preview performed no DDL.
    adopted = journal.adopt_lifecycle_schema(expected_legacy_digest=preview["legacy_digest"])
    assert adopted["migrated"] is True and adopted["schema_version"] == 2
    assert snapshot(journal) == before and journal.read("old") == original
    assert journal.begin(operation, "driver-binding", "invoke", {"text": "原文 😀", "actual": [1, 2]})["result"] == result
    again = journal.adopt_lifecycle_schema()
    assert again["migrated"] is False and snapshot(journal) == before
    reopened = DriverJournal(journal.path)
    assert columns(reopened)["message_id"][3] == 0 and reopened.read("old") == original


def test_adopted_journal_legacy_canonical_identity_remains_original_vector(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = legacy()
    row = journal.begin(operation, "driver-binding", "invoke", {"text": "hello"})
    original = '{"action":"invoke","binding_id":"driver-binding","command_id":"command-old","deadline":"2050-01-01T00:00:00+00:00","grant_ref":"actual-grant","message_id":"message-old","payload":{"text":"hello"}}'
    assert row["input_hash"] == hashlib.sha256(original.encode()).hexdigest()
    with sqlite3.connect(journal.path) as connection:
        stored = connection.execute("SELECT input_json,source_kind,source_ref,message_id FROM driver_operations").fetchone()
    assert stored == (original, "legacy", "old", "message-old")


def test_stale_preview_rejects_before_any_schema_change(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    preview = journal.preview_lifecycle_adoption()
    journal.event("existing", "observation", {"source": "controlled"})
    before = snapshot(journal)
    with pytest.raises(DriverRejected, match="changed since"):
        journal.adopt_lifecycle_schema(expected_legacy_digest=preview["legacy_digest"])
    assert snapshot(journal) == before and "source_ref" not in columns(journal)


def test_failed_adoption_rolls_back_ddl_copy_metadata_and_old_evidence(tmp_path, monkeypatch):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.begin(legacy(), "driver-binding", "invoke", {"text": "retained"})
    journal.event("old", "rpc_dispatch", {"method": "turn/start"})
    journal.finish("old", "uncertain", {"reason": "lost ACK"})
    before = snapshot(journal)

    def fault(_connection):
        raise RuntimeError("controlled post-copy verification fault")

    monkeypatch.setattr(journal, "_verify_lifecycle_schema", fault)
    with pytest.raises(RuntimeError, match="post-copy"):
        journal.adopt_lifecycle_schema()
    assert snapshot(journal) == before and columns(journal)["message_id"][3] == 1
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN "
            "('driver_journal_metadata','driver_operations_before_lifecycle_adoption')").fetchall() == []


@pytest.mark.parametrize("same_instance", [True, False])
def test_live_kernel_claim_rejects_operator_adoption(tmp_path, same_instance):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.begin(legacy(), "driver-binding", "invoke", {})
    journal.finish("old", "acknowledged", {"controlled": True})
    owner = journal if same_instance else DriverJournal(journal.path)
    descriptor, token = owner.claim_ownership("driver-binding")
    try:
        with pytest.raises(DriverRejected, match="quiesce"):
            journal.adopt_lifecycle_schema()
        assert "source_ref" not in columns(journal)
        owner.validate_claim(token, "driver-binding", descriptor)
    finally:
        owner.release_claim(token)
    assert journal.adopt_lifecycle_schema()["migrated"] is True


def test_unknown_legacy_input_blocks_lifecycle_after_adoption_without_new_rows(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.begin(legacy(), "driver-binding", "invoke", {"text": "original"})
    journal.finish("old", "uncertain", {"reason": "controlled unknown"})
    journal.adopt_lifecycle_schema()
    with pytest.raises(OutcomeUncertain, match="unresolved"):
        begin(journal, lifecycle())
    assert len(snapshot(journal)[0]) == 1 and journal.read("old")["state"] == "uncertain"


def test_lifecycle_has_null_message_and_exact_original_source_without_new_ledger(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = lifecycle()
    row = begin(journal, operation)
    assert row["input"]["source_kind"] == "receiver_lifecycle" and row["input"]["source_ref"] == "recovery-one"
    assert "message_id" not in row["input"] and not hasattr(operation, "message_id")
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT message_id,source_kind,source_ref FROM driver_operations").fetchone() == (
            None, "receiver_lifecycle", "recovery-one")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"driver_operations", "driver_events", "sqlite_sequence", "driver_journal_metadata"}


@pytest.mark.parametrize("change", ["deadline", "grant", "payload"])
def test_same_lifecycle_identity_never_silently_renews_or_changes_input(tmp_path, change):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = lifecycle()
    begin(journal, operation)
    journal.finish(operation.operation_id, "deferred", {"controlled": "no effect"})
    changed = replace(operation, **({"deadline": DEADLINE + timedelta(seconds=1)} if change == "deadline" else
                                   {"grant_ref": "different-grant"} if change == "grant" else {}))
    with pytest.raises(DriverRejected, match="different input"):
        begin(journal, changed, payload={"changed": True} if change == "payload" else {})
    assert journal.read(operation.operation_id)["state"] == "deferred"


@pytest.mark.parametrize("change", [{"action": "invoke"}, {"operation_id": "delivery-invocation:forged"},
    {"source_ref": "different-source"}, {"deadline": datetime(2000, 1, 1, tzinfo=UTC)},
    {"deadline": DEADLINE.replace(tzinfo=None)}, {"binding": {"node": "untrusted"}}])
def test_lifecycle_type_requires_stable_source_budget_and_actual_binding(change):
    with pytest.raises(DriverRejected):
        lifecycle(**change).validate()


@pytest.fixture(params=(CodexAppServerDriver, OpenCodeNativeDriver))
def driver(request, tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    calls = []

    def current(operation, observed):
        operation.validate()
        assert observed == BINDING
        calls.append(operation.operation_id)

    profile = SimpleNamespace(binding=lambda: {"controlled": "profile"})
    result = request.param("driver-binding", profile, journal, identity=BINDING, check_current=current)
    yield SimpleNamespace(driver=result, journal=journal, authorizations=calls)
    result.detach_transport()


def run(f, operation, *, action=None, payload=None, perform=None):
    return f.driver._run(operation, action or operation.action, payload or {"controlled": "input"},
        perform or (lambda: {"receipt_layer": "runtime_acknowledged", "fixture_only": True}))


@pytest.mark.parametrize("action", ["spawn", "resume"])
def test_actual_driver_run_uses_message_less_receipt_and_exact_cached_result(driver, action):
    operation = lifecycle(action=action)
    if action == "resume":
        if isinstance(driver.driver, CodexAppServerDriver):
            driver.driver.thread_id = operation.native_session_ref
        else:
            driver.driver.session_id = operation.native_session_ref
    effects = []

    def controlled():
        effects.append(True)
        return {"receipt_layer": "context_resumed", "fixture_only": True}

    first = run(driver, operation, perform=controlled)
    second = run(driver, operation, perform=lambda: pytest.fail("cached operation was reexecuted"))
    assert first == second and len(effects) == 1 and driver.authorizations
    assert first["source_ref"] == operation.source_ref and first["source_kind"] == "receiver_lifecycle"
    assert "message_id" not in first and "attempt_id" not in first and "dispatch_id" not in first
    assert driver.journal.read(operation.operation_id)["result"] == first


@pytest.mark.parametrize("action", ["invoke", "cancel", "terminate", "attach", "replace_session"])
def test_lifecycle_identity_cannot_reach_another_driver_action(driver, action):
    with pytest.raises(DriverRejected, match="action or immutable"):
        run(driver, lifecycle(), action=action, perform=lambda: pytest.fail("forbidden action reached effect"))
    assert snapshot(driver.journal)[0] == []


def test_current_node_callback_is_required_and_failure_precedes_journal_or_effect(driver):
    def missing(_operation, _binding):
        raise DriverRejected("fenced lifecycle Node verifier unavailable")

    driver.driver.check_current = missing
    with pytest.raises(DriverRejected, match="verifier unavailable"):
        run(driver, lifecycle(), perform=lambda: pytest.fail("no Node authority reached effect"))
    assert snapshot(driver.journal)[0] == []


@pytest.mark.parametrize("change", ["binding", "session"])
def test_driver_rechecks_exact_binding_and_resume_generation(driver, change):
    operation = lifecycle(action="resume")
    if isinstance(driver.driver, CodexAppServerDriver):
        driver.driver.thread_id = operation.native_session_ref
    else:
        driver.driver.session_id = operation.native_session_ref
    if change == "binding":
        operation = replace(operation, binding=replace(BINDING, node_boot_id="another-boot"))
    else:
        operation = replace(operation, native_session_ref="different-session")
    with pytest.raises(DriverRejected):
        run(driver, operation, perform=lambda: pytest.fail("changed target reached effect"))
    assert snapshot(driver.journal)[0] == []


def test_new_spawn_does_not_replace_an_existing_session_but_keeps_cached_positive_history(driver):
    operation = lifecycle()
    known = run(driver, operation)
    if isinstance(driver.driver, CodexAppServerDriver):
        driver.driver.thread_id = "existing-session"
    else:
        driver.driver.session_id = "existing-session"
    assert run(driver, operation) == known
    with pytest.raises(DriverRejected, match="cannot replace"):
        run(driver, lifecycle("another-recovery"), perform=lambda: pytest.fail("existing session replaced"))
    assert driver.journal.read(operation.operation_id)["result"] == known


def test_uncertain_lifecycle_never_executes_again_or_allows_fresh_source(driver):
    operation = lifecycle()
    calls = []

    def uncertain():
        calls.append(True)
        driver.journal.event(operation.operation_id, "process_dispatch", {"controlled": True})
        raise OSError("controlled ACK loss")

    with pytest.raises(OSError):
        run(driver, operation, perform=uncertain)
    with pytest.raises(OutcomeUncertain):
        run(driver, operation, perform=lambda: pytest.fail("uncertain operation replayed"))
    with pytest.raises(OutcomeUncertain):
        run(driver, lifecycle("new-source"), perform=lambda: pytest.fail("new session after unknown"))
    assert calls == [True] and driver.journal.read(operation.operation_id)["state"] == "uncertain"


def test_lifecycle_cannot_use_private_transport_to_submit_input(driver):
    operation = lifecycle()
    with pytest.raises(DriverRejected, match="cannot authorize"):
        if isinstance(driver.driver, CodexAppServerDriver):
            driver.driver._rpc(operation, "turn/start", {"text": "must not submit"})
        else:
            driver.driver._http(operation, "POST", "/session/ses_old/prompt_async", {"text": "must not submit"})
    assert snapshot(driver.journal)[0] == [] and snapshot(driver.journal)[1] == []


def test_lifecycle_adoption_never_changes_legacy_receipt_fields(driver):
    original = legacy("retained-message")
    result = driver.driver._run(original, "invoke", {"text": "controlled"},
        lambda: {"receipt_layer": "runtime_acknowledged", "fixture_only": True})
    assert result["message_id"] == original.message_id and "source_ref" not in result and "source_kind" not in result


@pytest.mark.parametrize("override_validate", [False, True])
@pytest.mark.parametrize("route", ["invoke", "terminate", "transport"])
def test_lifecycle_subclass_cannot_hide_as_legacy_message_operation(driver, override_validate, route):
    class Subtype(AuthorizedLifecycleOperation):
        @property
        def message_id(self):
            return "forged-message"

    class Overridden(Subtype):
        def validate(self, clock=None):
            return None

    forged = (Overridden if override_validate else Subtype)(**lifecycle().__dict__)
    called = []
    driver.driver.check_current = lambda operation, _binding: called.append(isinstance(operation, AuthorizedLifecycleOperation))
    with pytest.raises(DriverRejected):
        if route == "transport":
            if isinstance(driver.driver, CodexAppServerDriver):
                driver.driver._rpc(forged, "turn/start", {})
            else:
                driver.driver._http(forged, "POST", "/session/ses_old/prompt_async", {})
        else:
            run(driver, forged, action=route, perform=lambda: pytest.fail("subclass reached effect"))
    assert called == [] and snapshot(driver.journal)[0] == [] and snapshot(driver.journal)[1] == []


def test_codex_lifecycle_settings_can_read_the_actual_mcp_qualification_method(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    profile = SimpleNamespace(execution_mode="restricted", permission_profile="fixture", cwd=str(tmp_path),
        version="0.163.0", collaboration_server="actual-configured-acs", history_mode=None)
    driver = CodexAppServerDriver("driver-binding", profile, journal, identity=BINDING,
        check_current=lambda operation, observed: operation.check_target("driver-binding", observed, driver.thread_id))
    methods = []

    class ControlledRpc:
        def request(self, method, _params, **options):
            options["before_send"]()
            options["on_dispatch"]()
            methods.append(method)
            if method == "experimentalFeature/list":
                return {"data": [{"name": name, "enabled": False} for name in
                    ("multi_agent", "multi_agent_v2", "shell_tool", "request_permissions_tool", "apps", "plugins")]}
            if method == "permissionProfile/list":
                return {"data": [{"id": "fixture", "allowed": True}]}
            assert method == "mcpServerStatus/list"
            return {"data": [{"name": "actual-configured-acs", "runtimeStatus": "connected",
                              "tools": {name: {} for name in NATIVE_COLLABORATION_TOOLS}}]}

        def drain_events(self):
            return []

        def close(self):
            return None

    operation = lifecycle()

    def configured():
        # Controlled already-created context: no process or Native thread start.
        driver.thread_id = "controlled-thread"
        driver._settings(operation, {"activePermissionProfile": {"id": "fixture"}, "approvalPolicy": "never",
            "cwd": str(tmp_path), "sandbox": {"type": "readOnly", "networkAccess": False}})
        return {"receipt_layer": "context_resumed", "fixture_only": True}

    driver.client = ControlledRpc()
    try:
        result = driver._run(operation, "spawn", {"controlled": "profile"}, configured)
        assert methods == ["experimentalFeature/list", "permissionProfile/list", "mcpServerStatus/list"]
        assert result["source_ref"] == operation.source_ref and "message_id" not in result
    finally:
        driver.detach_transport()


def test_readopt_rejects_corrupted_lifecycle_discriminator_without_repair(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = lifecycle()
    begin(journal, operation)
    with sqlite3.connect(journal.path) as connection:
        connection.execute("UPDATE driver_operations SET source_ref='different-source'")
    with pytest.raises(DriverRejected, match="stored identity"):
        journal.adopt_lifecycle_schema()
    with pytest.raises(DriverRejected, match="stored identity"):
        begin(journal, operation)


@pytest.mark.parametrize("column,value", [("binding_id", "wrong-binding"), ("action", "resume"),
    ("command_id", "wrong-command"), ("message_id", "wrong-message")])
def test_legacy_adoption_rejects_mislabeled_rows_before_claim_probe_and_rolls_back(tmp_path, monkeypatch, column, value):
    import runtime.codex_driver as module

    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.begin(legacy(), "driver-binding", "invoke", {"text": "original"})
    journal.finish("old", "uncertain", {"reason": "original unknown"})
    with sqlite3.connect(journal.path) as connection:
        connection.execute("UPDATE driver_operations SET " + column + "=?", (value,))
    before = snapshot(journal)
    monkeypatch.setattr(module, "KernelClaim", lambda *_args: pytest.fail("corrupt SQL identity reached claim probing"))
    with pytest.raises(DriverRejected, match="stored identity"):
        journal.adopt_lifecycle_schema()
    assert snapshot(journal) == before and "source_kind" not in columns(journal)
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN "
            "('driver_journal_metadata','driver_operations_before_lifecycle_adoption')").fetchall() == []


@pytest.mark.parametrize("column,value", [("binding_id", "wrong-binding"), ("action", "resume"),
    ("operation_id", "receiver-lifecycle:" + "0" * 64)])
def test_readoption_rejects_sql_binding_action_and_lifecycle_id_corruption(tmp_path, column, value):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = lifecycle()
    begin(journal, operation)
    journal.finish(operation.operation_id, "uncertain", {"reason": "original unknown"})
    with sqlite3.connect(journal.path) as connection:
        connection.execute("UPDATE driver_operations SET " + column + "=?", (value,))
    before = snapshot(journal)
    with pytest.raises(DriverRejected, match="stored identity"):
        journal.adopt_lifecycle_schema()
    assert snapshot(journal) == before


def test_lifecycle_deterministic_id_cannot_be_relabelled_by_rehashing_another_action(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    operation = lifecycle()
    begin(journal, operation)
    with sqlite3.connect(journal.path) as connection:
        body = json.loads(connection.execute("SELECT input_json FROM driver_operations").fetchone()[0])
        body["action"] = "resume"
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        connection.execute("UPDATE driver_operations SET action='resume',input_json=?,input_hash=?",
                           (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
    before = snapshot(journal)
    with pytest.raises(DriverRejected, match="stored identity"):
        journal.adopt_lifecycle_schema()
    assert snapshot(journal) == before


@pytest.mark.parametrize("adopted", [False, True])
@pytest.mark.parametrize("column,value", [("binding_id", "wrong-binding"), ("action", "resume")])
def test_existing_begin_correlates_legacy_sql_identity_before_returning_cached_ack(tmp_path, adopted, column, value):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    if adopted:
        journal.adopt_lifecycle_schema()
    operation = legacy()
    journal.begin(operation, "driver-binding", "invoke", {"text": "original"})
    journal.finish("old", "acknowledged", {"native_ack_ref": "controlled old ACK"})
    with sqlite3.connect(journal.path) as connection:
        connection.execute("UPDATE driver_operations SET " + column + "=?", (value,))
    before = snapshot(journal)
    with pytest.raises(DriverRejected, match="stored identity"):
        journal.begin(operation, "driver-binding", "invoke", {"text": "original"})
    assert snapshot(journal) == before


@pytest.mark.parametrize("column,value", [("binding_id", "wrong-binding"), ("action", "resume")])
def test_corrupt_unknown_binding_or_action_never_hides_pending_input_from_driver(driver, column, value):
    original = lifecycle()
    begin(driver.journal, original)
    driver.journal.finish(original.operation_id, "uncertain", {"reason": "original unknown"})
    with sqlite3.connect(driver.journal.path) as connection:
        connection.execute("UPDATE driver_operations SET " + column + "=?", (value,))
    before = snapshot(driver.journal)
    for candidate in (original, lifecycle("another-recovery")):
        with pytest.raises(DriverRejected, match="stored identity"):
            run(driver, candidate, perform=lambda: pytest.fail("corrupt pending identity reached effect"))
    assert snapshot(driver.journal) == before and driver.journal.read(original.operation_id)["state"] == "uncertain"


def test_valid_unknown_other_binding_still_allows_an_independent_binding(tmp_path):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    journal.adopt_lifecycle_schema()
    original = lifecycle()
    begin(journal, original)
    journal.finish(original.operation_id, "uncertain", {"reason": "original unknown"})
    independent = lifecycle("independent", binding_id="independent-binding")
    accepted = journal.begin(independent, independent.binding_id, independent.action,
                             {"binding": asdict(independent.binding)})
    assert accepted["state"] == "intent"
    assert journal.read(original.operation_id)["state"] == "uncertain"

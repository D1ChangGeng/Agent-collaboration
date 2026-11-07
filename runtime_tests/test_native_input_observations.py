"""Read-only input observations from explicitly synthetic current-protocol responses."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.codex_driver import AuthorizedOperation, BindingIdentity, CodexAppServerDriver
from runtime.native_input_observations import observe_native_input
from runtime.opencode_driver import OpenCodeNativeDriver

ROOT = Path(__file__).resolve().parent
CODEX_SCHEMA = ROOT / "schema-0.153.2/codex_app_server_protocol.schemas.json"
OPENCODE_SCHEMAS = (ROOT / "schema-1.18.27/opencode-openapi.json", ROOT / "schema-1.18.31-opencode-openapi.json")


def permission(session="ses_current"):
    return {"id": "per_synthetic", "sessionID": session, "permission": "read",
            "patterns": ["synthetic private path"], "metadata": {"secret": "synthetic-private-prompt"}, "always": []}


def question(session="ses_current"):
    return {"id": "que_synthetic", "sessionID": session, "questions": [
        {"question": "synthetic-private-prompt", "header": "Fixture", "options": []}]}


def make_native(kind, tmp_path):
    codex = kind == "codex"
    driver = object.__new__(CodexAppServerDriver if codex else OpenCodeNativeDriver)
    driver.clock = None
    driver._lock = threading.RLock()
    driver.binding_id = "synthetic-binding"
    driver.identity = BindingIdentity("node", "boot", "runtime", "capacity", "slot", 1)
    driver.ownership = "exclusive_owned"
    driver.session_id = "synthetic-native-session" if codex else "ses_current"
    if codex:
        driver.thread_id = "thread_current"
    driver.owned = SimpleNamespace(birth_ref="synthetic-birth", containment_id="synthetic-job")
    state = SimpleNamespace(driver=driver, calls=[], status={"type": "idle"}, permissions=[], questions=[],
        statuses={"ses_current": {"type": "idle"}}, config={"provider": {"token": "synthetic-secret-token"}},
        proof={"verified": True, "root_exited": False, "birth_ref": "synthetic-birth", "containment_id": "synthetic-job"},
        document=json.loads(OPENCODE_SCHEMAS[0].read_text(encoding="utf-8")))
    config_path = tmp_path / "config.toml"
    config_path.write_text('approval_policy="never"\n', encoding="utf-8")
    schema_path = CODEX_SCHEMA if codex else OPENCODE_SCHEMAS[0]
    driver.profile = SimpleNamespace(schema_path=str(schema_path),
        schema_sha256=hashlib.sha256(schema_path.read_bytes()).hexdigest(), config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        codex_home=str(tmp_path), execution_mode="restricted")
    driver.check_current = lambda _operation, _identity: state.calls.append("authorize")

    def inspect_process(_owned):
        state.calls.append("process.inspect")
        return state.proof

    def readiness(_operation, *, before_status):
        state.calls.append("inspect_readiness")
        before_status()
        if codex:
            return {"thread": {"id": driver.thread_id, "sessionId": driver.session_id, "status": state.status}}
        return {"session": {"id": driver.session_id}, "status": state.status}

    def http(_operation, method, path, *, max_bytes):
        state.calls.append((method, path, max_bytes))
        assert method == "GET", "observation must never mutate Native state"
        responses = {"/doc": state.document, "/config": state.config, "/session/status": state.statuses,
                     "/permission": state.permissions, "/question": state.questions}
        value = responses[path]
        if isinstance(value, Exception):
            raise value
        return 200, value

    driver.supervisor = SimpleNamespace(inspect=inspect_process)
    driver.inspect_readiness = readiness
    driver._http = http
    driver.invoke = lambda *_args, **_kwargs: pytest.fail("observations cannot invoke input")
    driver.spawn = lambda *_args, **_kwargs: pytest.fail("observations cannot prepare receivers")
    state.operation = AuthorizedOperation("observe", "observe-command", "observe-message", "fixture-grant", None)
    return state


@pytest.fixture(params=("codex", "opencode"))
def native(request, tmp_path):
    return make_native(request.param, tmp_path)


@pytest.fixture
def codex_native(tmp_path):
    return make_native("codex", tmp_path)


@pytest.fixture
def opencode_native(tmp_path):
    return make_native("opencode", tmp_path)


def test_owned_idle_receiver_requires_current_schema_process_and_native_evidence(native):
    result = observe_native_input(native.driver, native.operation)
    assert result["dedicated_input"] and result["schema_verified"]
    assert {axis: item["value"] for axis, item in result["axes"].items()} == {
        "connection": "connected", "process": "present", "session": "present", "input": "ready", "blocker": "none"}
    assert all(item["knowledge"] == "observed" and item["evidence_ref"] for item in result["axes"].values())
    assert len(result["protocol_digest"]) == len(result["config_digest"]) == 64
    assert datetime.fromisoformat(result["expires_at"]) > datetime.fromisoformat(result["observed_at"])
    serialized = json.dumps(result)
    assert "synthetic-secret-token" not in serialized and "synthetic-private-prompt" not in serialized
    assert native.calls.count("process.inspect") == 2


@pytest.mark.parametrize("blocker", ["approval", "question"])
def test_exact_current_native_prompts_block_automatic_input(native, blocker):
    if isinstance(native.driver, CodexAppServerDriver):
        native.status = {"type": "active", "activeFlags": [
            "waitingOnApproval" if blocker == "approval" else "waitingOnUserInput"]}
    elif blocker == "approval":
        native.permissions = [permission()]
    else:
        native.questions = [question()]
    result = observe_native_input(native.driver, native.operation)
    assert result["axes"]["blocker"]["value"] == blocker
    assert result["axes"]["blocker"]["knowledge"] == "observed"
    assert "synthetic-private-prompt" not in json.dumps(result)


def test_busy_is_separate_from_blocker_and_never_implies_safe_queue(native):
    if isinstance(native.driver, CodexAppServerDriver):
        native.status = {"type": "active", "activeFlags": []}
    else:
        native.statuses["ses_current"] = {"type": "busy"}
    result = observe_native_input(native.driver, native.operation)
    assert result["axes"]["input"]["value"] == "busy"
    assert result["axes"]["blocker"]["value"] == "none"
    assert "safe_queue" not in result


def test_shared_attached_never_proves_dedicated_input_or_absent_user_draft(native):
    native.driver.ownership = "shared_attached"
    result = observe_native_input(native.driver, native.operation)
    assert result["dedicated_input"] is False
    assert result["axes"]["blocker"]["knowledge"] == "unknown"
    assert result["axes"]["blocker"]["value"] is None
    assert result["axes"]["blocker"]["reason_code"] == "native_input_ownership_unverified"


@pytest.mark.parametrize("change", [{"verified": False}, {"root_exited": True}, {"birth_ref": "other-process"},
                                     {"containment_id": "other-job"}])
def test_unverified_or_exited_process_never_proves_input_ownership(native, change):
    native.proof.update(change)
    result = observe_native_input(native.driver, native.operation)
    assert result["dedicated_input"] is False
    assert result["axes"]["blocker"]["value"] is None


def test_generation_change_during_readback_cannot_return_ready(native):
    original = native.driver.inspect_readiness

    def changed(*args, **kwargs):
        view = original(*args, **kwargs)
        native.driver.binding_id = "replacement-binding"
        return view

    native.driver.inspect_readiness = changed
    result = observe_native_input(native.driver, native.operation)
    assert result["native_session_ref"] is None and not result["dedicated_input"]
    assert all(item["value"] is None for item in result["axes"].values())


def test_stale_native_readback_is_unknown_instead_of_restamped(native):
    now = datetime.now(UTC)
    samples = iter((now, now, now + timedelta(seconds=3)))
    native.driver.clock = SimpleNamespace(observation_time=lambda: next(samples))
    result = observe_native_input(native.driver, native.operation)
    assert not result["dedicated_input"] and result["native_session_ref"] is None
    assert result["axes"]["input"]["value"] is None


def test_opencode_filters_pending_inventory_to_current_session(opencode_native):
    native = opencode_native
    native.permissions = [permission("ses_other")]
    native.questions = [question("ses_other")]
    result = observe_native_input(native.driver, native.operation)
    assert result["axes"]["blocker"]["value"] == "none"
    assert "ses_other" not in json.dumps(result)


@pytest.mark.parametrize("path,value", [("permissions", None), ("questions", {}),
    ("permissions", [{}]), ("questions", [{"id": "que_bad", "sessionID": "ses_other"}]),
    ("permissions", [permission()] * 129), ("permissions", [permission(), permission()]),
    ("permissions", OSError("synthetic pending API unavailable")), ("statuses", {}),
    ("statuses", {"ses_current": {"type": "unrecognized"}})])
def test_opencode_missing_malformed_or_unbounded_inventory_stays_unknown(opencode_native, path, value):
    native = opencode_native
    setattr(native, path, value)
    result = observe_native_input(native.driver, native.operation)
    assert result["axes"]["blocker"]["knowledge"] == "unknown"
    assert result["axes"]["blocker"]["value"] is None and not result["dedicated_input"]


@pytest.mark.parametrize("status", [{"type": "active"}, {"type": "active", "activeFlags": ["unknown"]},
    {"type": "idle", "activeFlags": ["waitingOnApproval"]}, {"type": "idle", "unexpected": True}])
def test_codex_unknown_or_inconsistent_active_flags_cannot_be_idle(codex_native, status):
    native = codex_native
    native.status = status
    result = observe_native_input(native.driver, native.operation)
    assert result["axes"]["input"]["knowledge"] == "unknown"
    assert result["axes"]["blocker"]["value"] is None


@pytest.mark.parametrize("schema", OPENCODE_SCHEMAS, ids=["1.18.27", "1.18.31"])
def test_opencode_paths_and_shapes_match_each_actual_pinned_schema(opencode_native, schema):
    native = opencode_native
    native.driver.profile.schema_path = str(schema)
    native.driver.profile.schema_sha256 = hashlib.sha256(schema.read_bytes()).hexdigest()
    native.document = json.loads(schema.read_text(encoding="utf-8"))
    assert observe_native_input(native.driver, native.operation)["schema_verified"]


def test_opencode_live_owner_schema_and_config_are_measured_without_missing_local_file(opencode_native, tmp_path):
    native = opencode_native
    native.driver.profile.execution_mode = "native"
    native.driver.profile.schema_path = str(tmp_path / "not-materialized.json")
    result = observe_native_input(native.driver, native.operation)
    assert result["schema_verified"] and result["axes"]["blocker"]["value"] == "none"
    assert result["protocol_digest"] and result["config_digest"]


@pytest.mark.parametrize("reference", ["$ref", "$dynamicRef", "$recursiveRef", "$otherRef"])
def test_opencode_changed_or_remote_schema_is_unknown_without_network_resolution(opencode_native, reference):
    native = opencode_native
    native.driver.profile.execution_mode = "native"
    native.document = copy.deepcopy(native.document)
    native.document["paths"]["/question"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {
        reference: "https://must-never-be-fetched.invalid/schema"}
    result = observe_native_input(native.driver, native.operation)
    assert result["schema_verified"] is False
    assert result["axes"]["blocker"]["value"] is None
    assert not any(isinstance(call, tuple) and call[1] == "/question" for call in native.calls)

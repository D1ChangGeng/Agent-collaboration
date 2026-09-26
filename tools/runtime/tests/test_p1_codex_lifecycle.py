"""Admission boundaries for one real Codex lifecycle evidence chain."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.codex_driver import OutcomeUncertain
from runtime.recovery_models import BoundaryRejected
from tools.runtime.p1_codex_lifecycle import (
    CodexSceneRejected,
    TurnBudget,
    collect_and_project_bounded,
    native_usage_observation,
    validate_lineage,
    validate_scene_profile,
    verify_budget_decision,
)
from tools.runtime.p1_profile_probe import (
    ProbeLedger,
    ProbeUnavailable,
    _run_codex_host_scene,
    availability,
)


def complete_readback() -> dict:
    attempt = "delivery-attempt-1"
    invocation = "delivery-invocation:" + attempt
    dispatch = "delivery-dispatch:" + attempt
    identity = ["message-1", "operation-1", attempt, invocation, dispatch]
    native = ["thread-1", "session-1", "turn-1"]
    return {
        "run_id": "run-1",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "machine_id": "fixture-machine",
        "node_id": "fixture-node",
        "message_id": identity[0],
        "command_id": "command-1",
        "operation_id": identity[1],
        "attempt_id": attempt,
        "invocation_id": invocation,
        "dispatch_id": dispatch,
        "thread_id": native[0],
        "session_id": native[1],
        "turn_id": native[2],
        "pg": {
            "identity": identity,
            "selection_machine_id": "fixture-machine",
            "selection_node_id": "fixture-node",
            "attempt_count": 1,
            "dispatch_marker_count": 1,
            "event_count": 1,
            "outbox_count": 1,
            "response_projection_count": 1,
            "response_receipt_count": 1,
        },
        "node": {
            "identity": identity,
            "machine_id": "fixture-machine",
            "node_id": "fixture-node",
            "mailbox_count": 1,
            "invocation_count": 1,
            "response_outbox_count": 1,
            "boot_current": True,
        },
        "temporal": {
            "operation_id": identity[1],
            "workflow_id": "acs-delivery/" + identity[1],
            "run_id": "temporal-run-1",
            "readback_status": "completed",
        },
        "driver": {
            "invocation_id": invocation,
            "native_identity": native,
            "turn_start_dispatch_count": 1,
            "turn_start_attempt_count": 1,
            "server_request_count": 0,
            "collect_read_count": 2,
            "terminal_status": "completed",
            "user_client_id": identity[0],
            "unique_user_message": True,
            "assistant_text_exact": True,
            "terminal_event_sha256": "c" * 64,
            "token_usage": {"status": "not_observed", "notification_count": 0},
        },
        "response": {
            "invocation_id": invocation,
            "native_identity": native,
            "disposition": "applied",
            "artifact_readback": True,
            "digest_match": True,
        },
        "os": {
            "termination_verified": True,
            "remaining_pids": [],
            "wrapper_exited": True,
            "environment_files_remaining": 0,
            "model_prompt_count": 1,
            "elapsed_seconds": 30,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    }


def scene_profile() -> dict:
    key_ref = "/home/review/.config/provider-key"
    return {
        "schema_version": "acs-p1-codex-scene/1",
        "native_executable_path": "/home/review/native/codex",
        "native_executable_sha256": "a" * 64,
        "native_executable_size": 1_000_000,
        "codex_version": "0.153.2",
        "schema_sha256": "b" * 64,
        "provider_alias": "fixture-provider",
        "provider_url": "https://provider.example.invalid/v1",
        "wire_api": "responses",
        "auth_command": "/usr/bin/cat",
        "auth_key_ref_path": key_ref,
        "auth_key_ref_path_sha256": hashlib.sha256(key_ref.encode()).hexdigest(),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "low",
        "model_catalog_entry": {
            "slug": "gpt-5.6-sol",
            "experimental_supported_tools": [],
        },
        "model_catalog_path": "/home/review/native/models.json",
        "model_catalog_sha256": "d" * 64,
        "model_catalog_size": 41_589,
        "max_turn_starts": 1,
        "max_collect_reads": 6,
        "max_elapsed_seconds": 120,
        "budget_evidence_ref": "P1-CODEX-LIFECYCLE-ONE-TURN-01",
    }


def test_token_usage_is_bound_to_original_thread_and_turn():
    usage = {
        "last": {
            "cachedInputTokens": 0,
            "inputTokens": 7,
            "outputTokens": 3,
            "reasoningOutputTokens": 1,
            "totalTokens": 10,
        },
        "total": {
            "cachedInputTokens": 0,
            "inputTokens": 7,
            "outputTokens": 3,
            "reasoningOutputTokens": 1,
            "totalTokens": 10,
        },
    }
    def event(thread: str, turn: str) -> tuple[str, dict]:
        return (
            "native_event",
            {"kind": "notification", "message": {
                "method": "thread/tokenUsage/updated",
                "params": {"threadId": thread, "turnId": turn, "tokenUsage": usage},
            }},
        )

    observed = native_usage_observation(
        [event("other-thread", "turn-1"), event("thread-1", "turn-1")],
        "thread-1", "turn-1",
    )
    assert observed["status"] == "observed"
    assert observed["notification_count"] == 1
    assert observed["last"]["totalTokens"] == 10
    assert native_usage_observation([event("other-thread", "turn-1")], "thread-1", "turn-1") == {
        "status": "not_observed", "notification_count": 0,
    }
    usage["last"]["totalTokens"] = -1
    with pytest.raises(CodexSceneRejected, match="token usage counts"):
        native_usage_observation([event("thread-1", "turn-1")], "thread-1", "turn-1")
    malformed = event("thread-1", "turn-1")
    del malformed[1]["message"]["params"]["tokenUsage"]
    with pytest.raises(CodexSceneRejected, match="token usage shape"):
        native_usage_observation([malformed], "thread-1", "turn-1")


def test_historical_model_file_does_not_enable_codex_gate_without_host_mode():
    old = {"codex_model_evidence": "/tmp/historical-model.json"}
    assert availability(old, "a" * 40)["P1-CODEX-LIFECYCLE"]["available"] is False
    planned = {**old, "codex_scene_mode": "same-run-host-node"}
    assert availability(planned, "a" * 40)["P1-CODEX-LIFECYCLE"]["available"] is True
    assert availability(planned, "a" * 40)["P1-INTEGRATED-ACCEPTANCE"]["available"] is False


def test_codex_host_adapter_missing_fixed_mounts_is_not_run(monkeypatch, tmp_path):
    for name in (
        "ACS_GATE_CODEX_PROFILE",
        "ACS_GATE_CODEX_PROFILE_SHA256",
        "ACS_GATE_BUDGET_DECISION_SHA256",
        "ACS_GATE_CODEX_HOST_READY",
        "ACS_GATE_CODEX_HOST_READY_SHA256",
        "ACS_GATE_CODEX_HOST_SOCKET",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProbeUnavailable, match="restricted Codex host mounts"):
        _run_codex_host_scene(
            {},
            ProbeLedger(tmp_path),
            "a" * 40,
            "b" * 40,
            "p1-run-" + "c" * 32,
            "c" * 24,
            datetime.now(UTC),
        )


def test_strict_scene_profile_accepts_only_bounded_provider_and_key_reference():
    value = scene_profile()
    assert validate_scene_profile(value) == value
    for field, changed in (
        ("provider_alias", "../bad"),
        ("provider_url", "http://different.invalid/v1"),
        ("provider_url", "https://u@provider.example.invalid/v1"),
        ("provider_url", "https://provider.example.invalid:bad/v1"),
        ("provider_url", "https://provider.example.invalid/v1#fragment"),
        ("auth_command", "/bin/sh"),
        ("auth_key_ref_path_sha256", "0" * 64),
        ("max_turn_starts", 2),
    ):
        candidate = copy.deepcopy(value)
        candidate[field] = changed
        with pytest.raises(CodexSceneRejected):
            validate_scene_profile(candidate)
    candidate = copy.deepcopy(value)
    candidate["model_catalog_entry"]["experimental_supported_tools"] = ["shell"]
    with pytest.raises(CodexSceneRejected):
        validate_scene_profile(candidate)


@pytest.mark.skipif(os.name != "posix", reason="private decision file is POSIX-only")
def test_budget_decision_binds_commit_tree_scene_and_one_turn(tmp_path: Path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    p = parent / "decision.json"
    value = {
        "schema_version": "acs-p1-model-request-budget/1",
        "decision_id": "P1-CODEX-LIFECYCLE-ONE-TURN-01",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "scene_profile_sha256": "c" * 64,
        "scenario_id": "P1-CODEX-LIFECYCLE",
        "provider_alias": "fixture-provider",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "low",
        "prompt": "Reply with exactly ACS_P1_CODEX_API_OK. Do not call tools.",
        "max_turn_starts": 1,
        "max_collect_reads": 6,
        "max_elapsed_seconds": 120,
        "retry_policy": "No second turn/start after uncertainty.",
        "spend_status": "Provider monetary cap not observed; cost unknown.",
        "tool_policy": "No tool invocation or delegation.",
    }
    p.write_text(json.dumps(value), encoding="utf-8")
    p.chmod(0o600)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    assert (
        verify_budget_decision(
            p,
            digest,
            source_commit="a" * 40,
            source_tree="b" * 40,
            scene_profile_sha256="c" * 64,
            decision_id="P1-CODEX-LIFECYCLE-ONE-TURN-01",
            provider_alias="fixture-provider",
            model="gpt-5.6-sol",
        )["monetary_cap"]
        == "unknown"
    )
    with pytest.raises(CodexSceneRejected, match="digest"):
        verify_budget_decision(
            p,
            "0" * 64,
            source_commit="a" * 40,
            source_tree="b" * 40,
            scene_profile_sha256="c" * 64,
            decision_id="P1-CODEX-LIFECYCLE-ONE-TURN-01",
            provider_alias="fixture-provider",
            model="gpt-5.6-sol",
        )
    with pytest.raises(CodexSceneRejected, match="content"):
        verify_budget_decision(
            p,
            digest,
            source_commit="d" * 40,
            source_tree="b" * 40,
            scene_profile_sha256="c" * 64,
            decision_id="P1-CODEX-LIFECYCLE-ONE-TURN-01",
            provider_alias="fixture-provider",
            model="gpt-5.6-sol",
        )
    with pytest.raises(CodexSceneRejected, match="content"):
        verify_budget_decision(
            p,
            digest,
            source_commit="a" * 40,
            source_tree="b" * 40,
            scene_profile_sha256="c" * 64,
            decision_id="P1-CODEX-LIFECYCLE-ONE-TURN-01",
            provider_alias="other-provider",
            model="gpt-5.6-sol",
        )


def test_complete_cross_authority_readback_is_admitted():
    assert validate_lineage(complete_readback())["model_calls"] == 1


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("pg", "attempt_count"), 2),
        (("pg", "attempt_count"), True),
        (("pg", "dispatch_marker_count"), 0),
        (("pg", "selection_machine_id"), "other-machine"),
        (("node", "mailbox_count"), 0),
        (("node", "machine_id"), "other-machine"),
        (("temporal", "workflow_id"), "other-workflow"),
        (("driver", "turn_start_dispatch_count"), 2),
        (("driver", "collect_read_count"), 7),
        (("driver", "collect_read_count"), "1"),
        (("driver", "server_request_count"), 1),
        (("driver", "terminal_event_sha256"), "changed"),
        (("driver", "user_client_id"), "other-message"),
        (("response", "disposition"), "fenced_late"),
        (("response", "artifact_readback"), False),
        (("os", "remaining_pids"), [123]),
        (("os", "environment_files_remaining"), 1),
        (("os", "model_prompt_count"), 2),
        (("os", "model_prompt_count"), True),
        (("os", "elapsed_seconds"), 121),
    ],
)
def test_mismatched_or_unbounded_layer_cannot_be_admitted(path, replacement):
    evidence = copy.deepcopy(complete_readback())
    evidence[path[0]][path[1]] = replacement
    with pytest.raises(CodexSceneRejected):
        validate_lineage(evidence)


def test_invocation_must_be_derived_from_prepared_attempt():
    evidence = complete_readback()
    evidence["attempt_id"] = "replacement-attempt"
    with pytest.raises(CodexSceneRejected, match="PG attempt"):
        validate_lineage(evidence)


def test_budget_refuses_extra_turn_or_unbounded_polling():
    with pytest.raises(CodexSceneRejected, match="budget"):
        TurnBudget(max_turn_starts=2)
    with pytest.raises(CodexSceneRejected, match="budget"):
        TurnBudget(max_collect_reads=100)


def test_bounded_collection_reuses_original_invocation_until_domain_projection():
    invocation = object()

    class Collector:
        def __init__(self):
            self.calls = []

        def collect_and_project(self, value):
            self.calls.append(value)
            if len(self.calls) == 1:
                raise OutcomeUncertain("native history not materialized")
            if len(self.calls) == 2:
                raise BoundaryRejected("Driver has no exact terminal response")
            return SimpleNamespace(disposition="applied")

    collector = Collector()
    result = collect_and_project_bounded(
        collector,
        invocation,
        budget=TurnBudget(max_collect_reads=3),
        pause=lambda _duration: None,
    )
    assert result.disposition == "applied"
    assert collector.calls == [invocation, invocation, invocation]


def test_bounded_collection_cannot_promote_missing_or_fenced_response():
    class Pending:
        calls = 0

        def collect_and_project(self, _value):
            self.calls += 1
            raise OutcomeUncertain("pending")

    collector = Pending()
    with pytest.raises(OutcomeUncertain, match="bounded terminal"):
        collect_and_project_bounded(
            collector,
            object(),
            budget=TurnBudget(max_collect_reads=2),
            pause=lambda _duration: None,
        )
    assert collector.calls == 2

    class Fenced:
        def collect_and_project(self, _value):
            return SimpleNamespace(disposition="fenced_late")

    with pytest.raises(CodexSceneRejected, match="not applied"):
        collect_and_project_bounded(Fenced(), object(), pause=lambda _duration: None)

    class ChangedIdentity:
        def collect_and_project(self, _value):
            raise BoundaryRejected("Driver terminal response lineage changed")

    with pytest.raises(BoundaryRejected, match="lineage changed"):
        collect_and_project_bounded(
            ChangedIdentity(),
            object(),
            pause=lambda _duration: None,
        )

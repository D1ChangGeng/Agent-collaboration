"""OpenCode runner pins one scene, budget, ready record and fixed host socket."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from tools.runtime import gate_runner as runner
from tools.runtime.p1_opencode_gate import DECISION_ID, MODEL_PROMPT
from tools.runtime.p1_opencode_probe import OpenCodeProbeRejected, _admission_and_ready
from tools.runtime.tests import test_gate_runner as gate_runner_tests
from tools.runtime.tests.test_p1_opencode_gate import scene


@pytest.fixture
def prepared():
    fixture = gate_runner_tests.GateRunnerTests(
        methodName="test_init_emits_only_not_run_and_invokes_offline_validator"
    )
    fixture.setUp()
    try:
        profile, _environment, _manifest = fixture.configure_runtime_profile()
        loopback = json.loads(profile.read_text())
        loopback["schema_version"] = "acs-p1-loopback-probe-profile/2"
        loopback["opencode_scene_mode"] = "same-run-host-node"
        profile.write_text(json.dumps(loopback), encoding="utf-8")
        profile.chmod(0o600)
        configured = fixture.plan["runtime_profile"]
        configured["profile_sha256"] = hashlib.sha256(profile.read_bytes()).hexdigest()
        private = fixture.base / "opencode-scene-private"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        scene_path = private / "scene.json"
        scene_path.write_text(json.dumps(scene()), encoding="utf-8")
        scene_path.chmod(0o600)
        scene_sha = hashlib.sha256(scene_path.read_bytes()).hexdigest()
        source = runner.source_identity(fixture.source)
        decision = {
            "schema_version": "acs-p1-model-request-budget/1",
            "decision_id": DECISION_ID,
            "source_commit": source.commit,
            "source_tree": source.tree,
            "scene_profile_sha256": scene_sha,
            "scenario_id": "P1-OPENCODE-LIFECYCLE",
            "provider_id": "fixture-provider",
            "model_id": "fixture-model",
            "prompt": MODEL_PROMPT,
            "max_prompt_async": 1,
            "max_collect_reads": 6,
            "max_elapsed_seconds": 120,
            "tool_policy": "No tool invocation or delegation.",
            "retry_policy": "No second prompt_async after uncertainty.",
            "spend_status": "Provider monetary cap not observed; cost unknown.",
        }
        budget = private / "budget.json"
        budget.write_text(json.dumps(decision), encoding="utf-8")
        budget.chmod(0o600)
        configured.update({
            "opencode_scene_profile": {"path": str(scene_path), "sha256": scene_sha},
            "opencode_budget_decision": {
                "path": str(budget),
                "sha256": hashlib.sha256(budget.read_bytes()).hexdigest(),
            },
        })
        fixture.write_plan()
        yield fixture, scene_path, budget, decision
    finally:
        fixture.tearDown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner pins")
def test_owner_scene_budget_mount_and_fixed_socket(prepared):
    fixture, scene_path, budget, _decision = prepared
    state = fixture.initialize()
    assert state["scenarios"]["P1-OPENCODE-LIFECYCLE"]["status"] == "not_run"
    env = runner.probe_environment(
        state, "P1-OPENCODE-LIFECYCLE", {"command_id": "fixture", "kind": "command_output"}
    )
    assert env["ACS_GATE_OPENCODE_PROFILE_SHA256"] == hashlib.sha256(scene_path.read_bytes()).hexdigest()
    assert env["ACS_GATE_OPENCODE_BUDGET_SHA256"] == hashlib.sha256(budget.read_bytes()).hexdigest()
    assert env["ACS_GATE_OPENCODE_BUDGET"] == "/run/acs-p1/opencode-budget.json"
    command = {
        "command_id": "fixture", "kind": "command_output", "argv": ["/bin/true"],
        "cwd": ".", "evidence_fields": ["raw_outputs"],
    }
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    root = parent / state["run_id"]
    root.mkdir(mode=0o700)
    observer = root / "observer"
    observer.mkdir(mode=0o700)
    ready = observer / "ready.json"
    ready.write_text(json.dumps({
        "schema_version": "acs-p1-opencode-host-ready/1", "run_id": state["run_id"],
        "source_commit": state["source_commit"], "source_tree": state["source_tree"],
        "scene_sha256": fixture.plan["runtime_profile"]["opencode_scene_profile"]["sha256"],
        "budget_sha256": fixture.plan["runtime_profile"]["opencode_budget_decision"]["sha256"],
        "machine_id": state["machine_id"], "node_id": state["node_id"],
    }), encoding="utf-8")
    ready.chmod(0o600)
    service = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    service.bind(str(observer / "host.sock"))
    os.chmod(observer / "host.sock", 0o600)
    service.listen(2)
    try:
        with runner.pinned_runtime_mounts(
            fixture.plan, state=state, scenario_id="P1-OPENCODE-LIFECYCLE",
            command=command, run_dir=fixture.run_dir,
        ) as (sources, descriptors):
            runner.assert_runtime_mounts_unchanged(fixture.plan, sources, descriptors)
            wrapped, _ = runner.sandbox_command(
                state, fixture.plan, fixture.run_dir,
                "P1-OPENCODE-LIFECYCLE", command, env, sources,
            )
            for name in (
                "opencode-profile.json", "opencode-budget.json",
                "opencode-ready.json", "opencode-host.sock",
            ):
                assert "/run/acs-p1/" + name in wrapped
            assert f"/run/user/{os.geteuid()}/bus" not in " ".join(wrapped)
    finally:
        service.close()
        assert root.resolve(strict=True).parent == parent.resolve(strict=True)
        shutil.rmtree(root)


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner pins")
@pytest.mark.parametrize("field", ["source_commit", "source_tree", "scene_profile_sha256"])
def test_changed_budget_source_or_scene_rejected_before_run(prepared, field):
    fixture, _scene, budget, decision = prepared
    decision[field] = "f" * (64 if field == "scene_profile_sha256" else 40)
    budget.write_text(json.dumps(decision), encoding="utf-8")
    fixture.plan["runtime_profile"]["opencode_budget_decision"]["sha256"] = hashlib.sha256(
        budget.read_bytes()
    ).hexdigest()
    fixture.write_plan()
    with pytest.raises(ValueError):
        fixture.initialize()
    assert not fixture.run_dir.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner pins")
def test_wrong_owner_mode_and_fixed_six_argv_rejected(prepared):
    fixture, scene_path, _budget, _decision = prepared
    scene_path.chmod(0o644)
    with pytest.raises(runner.PlanError):
        fixture.initialize()
    scene_path.chmod(0o600)
    fixture.plan["scenarios"]["P1-OPENCODE-LIFECYCLE"] = [{
        "command_id": "bad", "kind": "command_output", "argv": ["/bin/sh"],
        "evidence_fields": ["raw_outputs", "fault_injection"],
        "timeout_seconds": 300, "cwd": ".",
    }]
    with pytest.raises(runner.PlanError, match="fixed adapter"):
        runner.validate_plan(fixture.plan, fixture.contract)


def test_unmounted_open_code_ready_and_budget_fail_closed(monkeypatch):
    monkeypatch.delenv("ACS_GATE_OPENCODE_PROFILE", raising=False)
    with pytest.raises(OpenCodeProbeRejected, match="mounts"):
        _admission_and_ready({"node_id": "node"}, "a" * 40, "b" * 40,
                             "p1-run-" + "c" * 32)


def test_integrated_acceptance_requires_two_same_run_six_layer_records(tmp_path):
    state = {
        "runtime_profile": {
            "codex_scene_mode": "same-run-host-node",
            "opencode_scene_mode": "same-run-host-node",
            "codex_scene_profile_sha256": "a" * 64,
            "budget_decision_sha256": "b" * 64,
            "opencode_scene_profile_sha256": "c" * 64,
            "opencode_budget_decision_sha256": "d" * 64,
        },
        "scenarios": {
            "P1-CODEX-LIFECYCLE": {"status": "passed", "commands": {}},
            "P1-OPENCODE-LIFECYCLE": {"status": "not_run", "commands": {}},
        },
    }
    plan = {"scenarios": {
        "P1-CODEX-LIFECYCLE": [], "P1-OPENCODE-LIFECYCLE": [],
    }}
    with pytest.raises(runner.SandboxUnavailable, match="both same-run"):
        runner.verify_integrated_model_prerequisites(state, plan, tmp_path)
    state["runtime_profile"].pop("opencode_budget_decision_sha256")
    with pytest.raises(runner.SandboxUnavailable, match="owner-pinned"):
        runner.verify_integrated_model_prerequisites(state, plan, tmp_path)


def test_integrated_acceptance_checks_every_saved_layer_in_one_run(tmp_path, monkeypatch):
    run = "p1-run-" + "e" * 32
    state = {
        "run_id": run, "source_commit": "a" * 40, "source_tree": "b" * 40,
        "binding_sha256": "c" * 64, "machine_id": "machine-a", "node_id": "node-a",
        "version_binding": {"core": "fixture"},
        "runtime_profile": {
            "codex_scene_mode": "same-run-host-node",
            "opencode_scene_mode": "same-run-host-node",
            "codex_scene_profile_sha256": "a" * 64,
            "budget_decision_sha256": "b" * 64,
            "opencode_scene_profile_sha256": "c" * 64,
            "opencode_budget_decision_sha256": "d" * 64,
        },
        "scenarios": {},
    }
    plan = {"scenarios": {}}
    kinds = ("command_output", "postgresql", "sqlite", "temporal", "driver", "os")
    for name in ("P1-CODEX-LIFECYCLE", "P1-OPENCODE-LIFECYCLE"):
        commands = {}
        planned = []
        for kind in kinds:
            command_id = name + ":" + kind
            output = {
                "schema_version": runner.PROBE_SCHEMA, "status": "passed",
                "run_id": run, "source_commit": state["source_commit"],
                "source_tree": state["source_tree"], "scenario_id": name,
                "command_id": command_id, "evidence_kind": kind,
                "binding_sha256": state["binding_sha256"],
                "machine_id": state["machine_id"], "node_id": state["node_id"],
                "versions": state["version_binding"],
                "operation_ids": [name + ":op"], "message_ids": [name + ":message"],
                "event_ids": [name + ":event"], "receipt_ids": [name + ":receipt"],
                "facts": {"layer": {"readback": True}},
            }
            path = tmp_path / (name + "-" + kind + ".json")
            path.write_text(json.dumps(output), encoding="utf-8")
            commands[command_id] = {
                "status": "passed", "kind": kind,
                "output": runner.file_ref(path, tmp_path),
            }
            planned.append({"command_id": command_id, "kind": kind})
        state["scenarios"][name] = {"status": "passed", "commands": commands}
        plan["scenarios"][name] = planned
    observed = []
    monkeypatch.setattr(runner, "scenario_record", lambda _state, name, _root: observed.append(name))
    runner.verify_integrated_model_prerequisites(state, plan, tmp_path)
    assert observed == ["P1-CODEX-LIFECYCLE", "P1-OPENCODE-LIFECYCLE"]
    target = tmp_path / "P1-OPENCODE-LIFECYCLE-driver.json"
    changed = json.loads(target.read_text())
    changed["machine_id"] = "machine-b"
    target.write_text(json.dumps(changed), encoding="utf-8")
    state["scenarios"]["P1-OPENCODE-LIFECYCLE"]["commands"]["P1-OPENCODE-LIFECYCLE:driver"]["output"] = runner.file_ref(target, tmp_path)
    with pytest.raises(runner.EvidenceError, match="same HMAC run"):
        runner.verify_integrated_model_prerequisites(state, plan, tmp_path)

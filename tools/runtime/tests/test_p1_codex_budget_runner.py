"""Runner pins one future Codex scene and budget without enabling a Gate PASS."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from tools.runtime import gate_runner as runner
from tools.runtime.p1_codex_lifecycle import DECISION_ID, MODEL_PROMPT
from tools.runtime.tests import test_gate_runner as gate_runner_tests
from tools.runtime.tests.test_p1_codex_lifecycle import scene_profile


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
        loopback["codex_scene_mode"] = "same-run-host-node"
        profile.write_text(json.dumps(loopback), encoding="utf-8")
        profile.chmod(0o600)
        fixture.plan["runtime_profile"]["profile_sha256"] = hashlib.sha256(
            profile.read_bytes()
        ).hexdigest()
        private = fixture.base / "codex-scene-private"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        scene = private / "scene.json"
        scene.write_text(json.dumps(scene_profile()), encoding="utf-8")
        scene.chmod(0o600)
        scene_sha = hashlib.sha256(scene.read_bytes()).hexdigest()
        source = runner.source_identity(fixture.source)
        decision = {
            "schema_version": "acs-p1-model-request-budget/1",
            "decision_id": DECISION_ID,
            "source_commit": source.commit,
            "source_tree": source.tree,
            "scene_profile_sha256": scene_sha,
            "scenario_id": "P1-CODEX-LIFECYCLE",
            "provider_alias": "fixture-provider",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "low",
            "prompt": MODEL_PROMPT,
            "max_turn_starts": 1,
            "max_collect_reads": 6,
            "max_elapsed_seconds": 120,
            "retry_policy": "No second turn/start after uncertainty.",
            "spend_status": "Provider monetary cap not observed; cost unknown.",
            "tool_policy": "No tool invocation or delegation.",
        }
        budget = private / "budget.json"
        budget.write_text(json.dumps(decision), encoding="utf-8")
        budget.chmod(0o600)
        fixture.plan["runtime_profile"].update(
            {
                "codex_scene_profile": {"path": str(scene), "sha256": scene_sha},
                "budget_decision": {
                    "path": str(budget),
                    "sha256": hashlib.sha256(budget.read_bytes()).hexdigest(),
                },
            }
        )
        fixture.write_plan()
        yield fixture, scene, budget, decision
    finally:
        fixture.tearDown()


@pytest.mark.skipif(os.name != "posix", reason="owner-only runner pin requires POSIX")
def test_exact_commit_tree_scene_budget_mounts_but_gate_remains_not_run(prepared):
    fixture, scene, budget, _decision = prepared
    state = fixture.initialize()
    assert state["scenarios"]["P1-CODEX-LIFECYCLE"]["status"] == "not_run"
    assert state["runtime_profile"]["codex_scene_mode"] == "same-run-host-node"
    env = runner.probe_environment(
        state,
        "P1-CODEX-LIFECYCLE",
        {
            "command_id": "codex-probe",
            "kind": "command_output",
            "argv": ["/bin/true"],
        },
    )
    assert env["ACS_GATE_CODEX_PROFILE"] == "/run/acs-p1/codex-profile.json"
    assert env["ACS_GATE_CODEX_PROFILE_SHA256"] == hashlib.sha256(scene.read_bytes()).hexdigest()
    assert env["ACS_GATE_BUDGET_DECISION_SHA256"] == hashlib.sha256(budget.read_bytes()).hexdigest()
    command = {
        "command_id": "codex-probe",
        "kind": "command_output",
        "argv": ["/bin/true"],
        "cwd": ".",
        "evidence_fields": ["raw_outputs"],
    }
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-codex")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    root = parent / state["run_id"]
    root.mkdir(mode=0o700)
    observer = root / "observer"
    observer.mkdir(mode=0o700)
    ready = observer / "ready.json"
    ready.write_text(
        json.dumps(
            {
                "schema_version": "acs-p1-codex-host-ready/1",
                "run_id": state["run_id"],
                "source_commit": state["source_commit"],
                "source_tree": state["source_tree"],
                "scene_sha256": fixture.plan["runtime_profile"]["codex_scene_profile"]["sha256"],
                "budget_sha256": fixture.plan["runtime_profile"]["budget_decision"]["sha256"],
            }
        ),
        encoding="utf-8",
    )
    ready.chmod(0o600)
    service = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    service.bind(str(observer / "host.sock"))
    os.chmod(observer / "host.sock", 0o600)
    service.listen(2)
    try:
        with runner.pinned_runtime_mounts(
            fixture.plan,
            state=state,
            scenario_id="P1-CODEX-LIFECYCLE",
            command=command,
            run_dir=fixture.run_dir,
        ) as (sources, descriptors):
            runner.assert_runtime_mounts_unchanged(fixture.plan, sources, descriptors)
            wrapped, _output = runner.sandbox_command(
                state,
                fixture.plan,
                fixture.run_dir,
                "P1-CODEX-LIFECYCLE",
                command,
                env,
                sources,
            )
            assert "--ro-bind" in wrapped
            assert "/run/acs-p1/codex-profile.json" in wrapped
            assert "/run/acs-p1/budget-decision.json" in wrapped
            assert "/run/acs-p1/codex-ready.json" in wrapped
            assert "/run/acs-p1/codex-host.sock" in wrapped
            assert f"/run/user/{os.geteuid()}/bus" not in " ".join(wrapped)
    finally:
        service.close()
        assert root.resolve(strict=True).parent == parent.resolve(strict=True)
        shutil.rmtree(root)


@pytest.mark.skipif(os.name != "posix", reason="owner-only runner pin requires POSIX")
@pytest.mark.parametrize("field", ["source_commit", "source_tree", "scene_profile_sha256"])
def test_budget_binding_mismatch_rejected_before_run(prepared, field):
    fixture, _scene, budget, decision = prepared
    decision[field] = "f" * (40 if field != "scene_profile_sha256" else 64)
    budget.write_text(json.dumps(decision), encoding="utf-8")
    fixture.plan["runtime_profile"]["budget_decision"]["sha256"] = hashlib.sha256(
        budget.read_bytes()
    ).hexdigest()
    fixture.write_plan()
    with pytest.raises(ValueError):
        fixture.initialize()
    assert not fixture.run_dir.exists()


@pytest.mark.skipif(os.name != "posix", reason="owner-only runner pin requires POSIX")
def test_owner_mode_or_sha_change_is_rejected(prepared):
    fixture, scene, _budget, _decision = prepared
    scene.chmod(0o644)
    with pytest.raises(runner.PlanError):
        fixture.initialize()
    scene.chmod(0o600)
    fixture.plan["runtime_profile"]["codex_scene_profile"]["sha256"] = "0" * 64
    fixture.write_plan()
    with pytest.raises(runner.PlanError):
        fixture.initialize()


@pytest.mark.skipif(os.name != "posix", reason="owner-only runner pin requires POSIX")
def test_codex_plan_only_accepts_the_fixed_six_layer_probe_argv(prepared):
    fixture, _scene, _budget, _decision = prepared
    kinds = ("command_output", "postgresql", "sqlite", "temporal", "driver", "os")
    fixture.plan["scenarios"]["P1-CODEX-LIFECYCLE"] = [
        {
            "command_id": f"codex:{kind}",
            "kind": kind,
            "argv": [
                "/run/acs-p1/runtime/bin/python",
                "/mnt/tools/runtime/p1_profile_probe.py",
                "run",
                "--profile",
                "/run/acs-p1/profile.json",
                "--scenario",
                "P1-CODEX-LIFECYCLE",
                "--kind",
                kind,
                "--output",
                "/srv",
            ],
            "evidence_fields": list(
                {
                    "command_output": ("raw_outputs", "fault_injection"),
                    "postgresql": ("receipts",),
                    "sqlite": ("artifact_readback",),
                    "temporal": ("recovery_trace",),
                    "driver": ("effect_readback",),
                    "os": ("source_readback",),
                }[kind]
            ),
            "timeout_seconds": 300,
            "cwd": ".",
        }
        for kind in kinds
    ]
    assert runner.validate_plan(fixture.plan, fixture.contract) is fixture.plan
    fixture.plan["scenarios"]["P1-CODEX-LIFECYCLE"][0]["argv"] = ["/bin/sh"]
    with pytest.raises(runner.PlanError, match="fixed adapter"):
        runner.validate_plan(fixture.plan, fixture.contract)


@pytest.mark.skipif(os.name != "posix", reason="owner-only runner pin requires POSIX")
def test_missing_owner_key_keeps_complete_codex_plan_not_run_before_pg(prepared):
    fixture, _scene, _budget, _decision = prepared
    from tools.runtime.p1_profile_probe import EVIDENCE_FIELDS, KINDS

    fixture.plan["scenarios"]["P1-CODEX-LIFECYCLE"] = [
        {
            "command_id": f"codex:{kind}",
            "kind": kind,
            "argv": [
                "/run/acs-p1/runtime/bin/python",
                "/mnt/tools/runtime/p1_profile_probe.py",
                "run",
                "--profile",
                "/run/acs-p1/profile.json",
                "--scenario",
                "P1-CODEX-LIFECYCLE",
                "--kind",
                kind,
                "--output",
                "/srv",
            ],
            "evidence_fields": list(EVIDENCE_FIELDS[kind]),
            "timeout_seconds": 300,
            "cwd": ".",
        }
        for kind in KINDS
    ]
    fixture.write_plan()
    state = fixture.initialize()
    with pytest.raises(runner.SandboxUnavailable, match="host capacity"):
        runner.run_scenario(
            fixture.run_dir,
            fixture.source,
            fixture.contract_path,
            "P1-CODEX-LIFECYCLE",
        )
    after = runner.load_state(fixture.run_dir)
    assert after["scenarios"]["P1-CODEX-LIFECYCLE"]["status"] == "not_run"
    assert after["gate_status"] == "not_run"
    root = Path(f"/run/user/{os.geteuid()}/acs-p1-codex") / state["run_id"]
    assert not root.exists()

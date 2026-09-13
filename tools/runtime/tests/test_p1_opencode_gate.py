"""Future model admission needs owner files and the exact same-run identity."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.runtime.p1_opencode_gate import (
    DECISION_ID,
    MODEL_PROMPT,
    SCHEMA_SHA256,
    OpenCodeGateAdmission,
    OpenCodeGateRejected,
    validate_scene,
)
from tools.runtime.tests.test_p1_opencode_readback import complete

RUN_ID = "p1-run-" + "c" * 32


def scene() -> dict:
    key = "/home/review/private/provider-key"
    return {
        "schema_version": "acs-p1-opencode-scene/1",
        "native_executable_path": "/home/review/native/opencode",
        "native_executable_sha256": "a" * 64,
        "native_executable_size": 184_825_984,
        "opencode_version": "1.18.30",
        "schema_sha256": SCHEMA_SHA256,
        "provider_id": "fixture-provider",
        "provider_url": "https://provider.example.invalid/v1",
        "model_id": "fixture-model",
        "agent": "engineer",
        "auth_key_ref_path": key,
        "auth_key_ref_path_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "config_template_path": "/home/review/private/opencode.json",
        "config_sha256": "d" * 64,
        "max_prompt_async": 1,
        "max_collect_reads": 6,
        "max_elapsed_seconds": 120,
        "budget_evidence_ref": DECISION_ID,
    }


def decision(scene_sha: str) -> dict:
    return {
        "schema_version": "acs-p1-model-request-budget/1",
        "decision_id": DECISION_ID,
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
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


def _write(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scene_rejects_route_or_budget_expansion():
    assert validate_scene(scene())["max_prompt_async"] == 1
    for field, changed in (
        ("provider_url", "http://provider.example.invalid/v1"),
        ("provider_url", "https://u@provider.example.invalid/v1"),
        ("provider_id", "../outside"),
        ("max_prompt_async", 2),
        ("max_collect_reads", 7),
        ("auth_key_ref_path_sha256", "0" * 64),
    ):
        candidate = copy.deepcopy(scene())
        candidate[field] = changed
        with pytest.raises(OpenCodeGateRejected):
            validate_scene(candidate)


@pytest.mark.skipif(os.name != "posix", reason="owner-only decision requires POSIX")
def test_owner_budget_binds_source_scene_run_machine_and_one_prompt(tmp_path: Path):
    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    scene_path, budget_path = private / "scene.json", private / "decision.json"
    scene_sha = _write(scene_path, scene())
    budget_sha = _write(budget_path, decision(scene_sha))
    kwargs = {
        "source_commit": "a" * 40, "source_tree": "b" * 40,
    }
    admission = OpenCodeGateAdmission.load(
        scene_path, scene_sha, budget_path, budget_sha, **kwargs
    ).bind_run(RUN_ID, "machine-a", "node-a")
    lineage = complete()
    lineage["run_id"] = RUN_ID
    lineage["os"]["unit"] = "acs-" + RUN_ID + ".service"
    assert admission.assert_final_lineage(lineage)["run_id"] == RUN_ID
    for changed in (
        {**kwargs, "source_commit": "d" * 40},
        {**kwargs, "source_tree": "d" * 40},
    ):
        with pytest.raises(OpenCodeGateRejected):
            OpenCodeGateAdmission.load(
                scene_path, scene_sha, budget_path, budget_sha, **changed
            )
    for changed_run in (
        admission.bind_run("p1-run-" + "d" * 32, "machine-a", "node-a"),
        admission.bind_run(RUN_ID, "other-machine", "node-a"),
        admission.bind_run(RUN_ID, "machine-a", "other-node"),
    ):
        with pytest.raises(OpenCodeGateRejected, match="exact source"):
            changed_run.assert_final_lineage(lineage)
    altered = decision(scene_sha)
    altered["provider_id"] = "replacement-provider"
    wrong_budget_sha = _write(budget_path, altered)
    with pytest.raises(OpenCodeGateRejected, match="decision"):
        OpenCodeGateAdmission.load(
            scene_path, scene_sha, budget_path, wrong_budget_sha, **kwargs
        )
    budget_path.chmod(0o644)
    with pytest.raises(OpenCodeGateRejected, match="owner file"):
        OpenCodeGateAdmission.load(
            scene_path, scene_sha, budget_path, wrong_budget_sha, **kwargs
        )


@pytest.mark.skipif(os.name != "posix", reason="owner-only key attestation requires POSIX")
def test_key_reference_is_owner_single_link_and_no_follow(tmp_path: Path):
    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    key = private / "provider-key"
    key.write_bytes(b"fixture-only")
    key.chmod(0o600)
    value = scene()
    value["auth_key_ref_path"] = str(key)
    value["auth_key_ref_path_sha256"] = hashlib.sha256(str(key).encode()).hexdigest()
    scene_path, budget_path = private / "scene.json", private / "decision.json"
    scene_sha = _write(scene_path, value)
    budget_sha = _write(budget_path, decision(scene_sha))
    admission = OpenCodeGateAdmission.load(
        scene_path, scene_sha, budget_path, budget_sha,
        source_commit="a" * 40, source_tree="b" * 40,
    )
    assert admission.key_reference_identity()[1] == key.stat().st_ino
    key.chmod(0o644)
    with pytest.raises(OpenCodeGateRejected, match="inode or mode"):
        admission.key_reference_identity()
    key.chmod(0o600)
    key.unlink()
    key.symlink_to(scene_path)
    with pytest.raises(OpenCodeGateRejected, match="inode or mode"):
        admission.key_reference_identity()


@pytest.mark.skipif(os.name != "posix", reason="owner-only provider config requires POSIX")
def test_actual_config_route_is_bound_to_scene_digest(tmp_path: Path):
    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    config = private / "opencode.json"

    def stage(route: str):
        config_sha = _write(config, {
            "model": "fixture-provider/fixture-model",
            "agent": {"engineer": {"model": "fixture-provider/fixture-model"}},
            "provider": {"fixture-provider": {"options": {"baseURL": route}}},
        })
        value = scene()
        value["config_template_path"] = str(config)
        value["config_sha256"] = config_sha
        scene_path, budget_path = private / "scene.json", private / "decision.json"
        scene_sha = _write(scene_path, value)
        budget_sha = _write(budget_path, decision(scene_sha))
        admission = OpenCodeGateAdmission.load(
            scene_path, scene_sha, budget_path, budget_sha,
            source_commit="a" * 40, source_tree="b" * 40,
        ).bind_run(RUN_ID, "machine-a", "node-a")
        profile = SimpleNamespace(
            version="1.18.30", executable_sha256=value["native_executable_sha256"],
            schema_sha256=value["schema_sha256"], config_sha256=config_sha,
            provider_id=value["provider_id"], model_id=value["model_id"],
            agent="engineer", config_path=config,
        )
        return admission, profile

    admission, profile = stage("https://provider.example.invalid/v1")
    admission.assert_native_profile(profile)
    assert hashlib.sha256(admission.config_template_bytes()).hexdigest() == profile.config_sha256
    admission, profile = stage("https://different.example.invalid/v1")
    with pytest.raises(OpenCodeGateRejected, match="provider config route"):
        admission.assert_native_profile(profile)
    with pytest.raises(OpenCodeGateRejected, match="config template route"):
        admission.config_template_bytes()
    config.chmod(0o644)
    with pytest.raises(OpenCodeGateRejected, match="owner file"):
        admission.assert_native_profile(profile)


@pytest.mark.skipif(os.name == "posix", reason="Windows boundary")
def test_windows_owner_budget_fails_closed(tmp_path: Path):
    with pytest.raises(OpenCodeGateRejected, match="POSIX"):
        OpenCodeGateAdmission.load(
            tmp_path / "scene.json", "0" * 64,
            tmp_path / "decision.json", "0" * 64,
            source_commit="a" * 40, source_tree="b" * 40,
        )

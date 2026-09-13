"""Owner XDG auth staging uses exactly one pinned key and provider namespace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from runtime.opencode_driver import OpenCodeLaunchProfile
from tools.runtime import p1_opencode_auth as auth_module
from tools.runtime.p1_opencode_auth import PrivateOpenCodeAuth
from tools.runtime.p1_opencode_gate import OpenCodeGateAdmission, OpenCodeGateRejected
from tools.runtime.tests.test_p1_opencode_gate import decision, scene


@pytest.fixture
def fixture():
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("owner auth staging requires a non-root POSIX user")
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    run_id = "p1-run-" + uuid.uuid4().hex
    root = parent / run_id
    root.mkdir(mode=0o700)
    for name in ("data", "config", "input"):
        (root / name).mkdir(mode=0o700)
    config_dir = root / "config" / "opencode"
    config_dir.mkdir(mode=0o700)
    key = root / "input" / "key"
    key.write_bytes(b"fixture-only-key")
    key.chmod(0o600)
    config = config_dir / "opencode.json"
    config.write_text(json.dumps({
        "model": "fixture-provider/fixture-model",
        "agent": {"engineer": {"model": "fixture-provider/fixture-model"}},
        "provider": {"fixture-provider": {
            "npm": "@ai-sdk/openai", "options": {"baseURL": "https://provider.example.invalid/v1"},
            "models": {"fixture-model": {"name": "Fixture"}},
        }},
    }), encoding="utf-8")
    config.chmod(0o600)
    value = scene()
    value.update({
        "auth_key_ref_path": str(key),
        "auth_key_ref_path_sha256": hashlib.sha256(str(key).encode()).hexdigest(),
        "config_template_path": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    })
    scene_path = root / "input" / "scene.json"
    scene_path.write_text(json.dumps(value), encoding="utf-8")
    scene_path.chmod(0o600)
    scene_sha = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    budget = root / "input" / "budget.json"
    budget.write_text(json.dumps(decision(scene_sha)), encoding="utf-8")
    budget.chmod(0o600)
    admission = OpenCodeGateAdmission.load(
        scene_path, scene_sha, budget,
        hashlib.sha256(budget.read_bytes()).hexdigest(),
        source_commit="a" * 40, source_tree="b" * 40,
    ).bind_run(run_id, "machine-fixture", "node-fixture")
    profile = OpenCodeLaunchProfile(
        str(root / "bin" / "opencode"), value["native_executable_sha256"],
        "1.18.30", str(root / "schema.json"), value["schema_sha256"],
        str(root / "input"), str(root / "home"), str(root / "config"),
        str(root / "data"), str(root / "state"), str(root / "cache"),
        str(root / "tmp"), value["config_sha256"], "engineer",
        "fixture-provider", "fixture-model", {},
    )
    try:
        yield admission, profile, root, key
    finally:
        assert root.resolve(strict=True).parent == parent.resolve(strict=True)
        shutil.rmtree(root)


def test_private_auth_stage_and_source_or_stage_tamper_rejected(fixture):
    admission, profile, root, key = fixture
    stager = PrivateOpenCodeAuth(admission)
    assert stager.stage(profile)["same_reference"] is True
    assert stager.assert_current(profile)["owner_mode"] == "0600"
    auth = root / "data" / "opencode" / "auth.json"
    assert auth.stat().st_mode & 0o777 == 0o600
    assert json.loads(auth.read_text()) == {
        "fixture-provider": {"type": "api", "key": "fixture-only-key"}
    }
    with pytest.raises(OpenCodeGateRejected, match="already staged"):
        stager.stage(profile)
    key.write_bytes(b"rotated-fixture")
    with pytest.raises(OpenCodeGateRejected):
        stager.assert_current(profile)
    key.write_bytes(b"fixture-only-key")
    auth.chmod(0o644)
    with pytest.raises(OpenCodeGateRejected):
        stager.assert_current(profile)


def test_symlink_or_wrong_provider_namespace_rejected(fixture):
    admission, profile, root, key = fixture
    stager = PrivateOpenCodeAuth(admission)
    key.unlink()
    key.symlink_to(root / "input" / "scene.json")
    with pytest.raises(OpenCodeGateRejected):
        stager.stage(profile)
    key.unlink()
    key.write_bytes(b"fixture-only-key")
    key.chmod(0o600)
    with pytest.raises(OpenCodeGateRejected, match="reference changed"):
        stager.stage(profile)


def test_post_publish_validation_failure_removes_owner_secret_file(fixture, monkeypatch):
    admission, profile, root, _key = fixture
    stager = PrivateOpenCodeAuth(admission)
    monkeypatch.setattr(
        stager, "_read_staged",
        lambda *_args: (_ for _ in ()).throw(OpenCodeGateRejected("fixture post-publish failure")),
    )
    with pytest.raises(OpenCodeGateRejected):
        stager.stage(profile)
    assert not (root / "data" / "opencode" / "auth.json").exists()
    assert not (root / "data" / "opencode").exists()
    assert stager.staged_identity is None


def test_zero_byte_auth_stage_write_fails_and_cleans(fixture, monkeypatch):
    admission, profile, root, _key = fixture
    stager = PrivateOpenCodeAuth(admission)
    monkeypatch.setattr(auth_module.os, "write", lambda *_args: 0)
    with pytest.raises(OpenCodeGateRejected, match="no progress"):
        stager.stage(profile)
    assert not (root / "data" / "opencode" / "auth.json").exists()
    assert not (root / "data" / "opencode").exists()

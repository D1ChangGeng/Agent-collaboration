"""OpenCode host setup and postflight fail closed before any model request."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.runtime import p1_opencode_host_factory as factory
from tools.runtime.p1_opencode_gate import (
    DECISION_ID,
    MODEL_PROMPT,
    OpenCodeGateRejected,
)
from tools.runtime.p1_opencode_host_scene import postflight_opencode_run
from tools.runtime.tests.test_p1_opencode_gate import scene


@pytest.mark.skipif(os.name != "posix", reason="owner-only host capacity requires POSIX")
def test_missing_key_reference_cannot_create_schema_or_host_root(tmp_path, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("non-root owner required")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    run_id = "p1-run-" + uuid.uuid4().hex
    value = scene()
    value["auth_key_ref_path"] = str(private / "missing-key")
    value["auth_key_ref_path_sha256"] = hashlib.sha256(
        value["auth_key_ref_path"].encode()
    ).hexdigest()
    scene_path = private / "scene.json"
    scene_path.write_text(json.dumps(value), encoding="utf-8")
    scene_path.chmod(0o600)
    scene_sha = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    decision_path = private / "decision.json"
    decision_path.write_text(json.dumps({
        "schema_version": "acs-p1-model-request-budget/1",
        "decision_id": DECISION_ID,
        "source_commit": "a" * 40, "source_tree": "b" * 40,
        "scene_profile_sha256": scene_sha, "scenario_id": "P1-OPENCODE-LIFECYCLE",
        "provider_id": value["provider_id"], "model_id": value["model_id"],
        "prompt": MODEL_PROMPT, "max_prompt_async": 1, "max_collect_reads": 6,
        "max_elapsed_seconds": 120, "tool_policy": "No tool invocation or delegation.",
        "retry_policy": "No second prompt_async after uncertainty.",
        "spend_status": "Provider monetary cap not observed; cost unknown.",
    }), encoding="utf-8")
    decision_path.chmod(0o600)
    decision_sha = hashlib.sha256(decision_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        factory.psycopg, "connect",
        lambda *args, **kwargs: pytest.fail("PostgreSQL reached before key admission"),
    )
    with pytest.raises(OpenCodeGateRejected, match="key reference"):
        factory.prepare_opencode_host_capacity(
            {
                "postgres_dsn": "postgresql://fixture:value@127.0.0.1:54329/temporal",
                "temporal_endpoint": "127.0.0.1:7239",
                "temporal_namespace": "default",
                "node_id": "fixture-node",
            },
            scene_path=scene_path, scene_sha256=scene_sha,
            budget_path=decision_path, budget_sha256=decision_sha,
            run_id=run_id, source_commit="a" * 40, source_tree="b" * 40,
            machine_id="fixture-machine", node_id="fixture-node",
            source_snapshot=tmp_path,
            plan_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    assert not (Path(f"/run/user/{os.geteuid()}/acs-p1-opencode") / run_id).exists()


@pytest.mark.skipif(os.name != "posix", reason="Systemd postflight requires POSIX")
def test_environment_file_residue_blocks_clean_postflight():
    if os.geteuid() == 0 or not Path(f"/run/user/{os.geteuid()}/bus").exists():
        pytest.skip("non-root user manager required")
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    run_id = "p1-run-" + uuid.uuid4().hex
    root = parent / run_id
    root.mkdir(mode=0o700)
    (root / "ledger").mkdir(mode=0o700)
    environment = root / "systemd-env"
    environment.mkdir(mode=0o700)
    residue = environment / "leftover.env"
    residue.write_text("FIXTURE=1\n", encoding="utf-8")
    residue.chmod(0o600)
    try:
        observed = postflight_opencode_run(root, run_id)
        assert observed["status"] == "uncertain"
        assert observed["environment_files_remaining"] == 1
        residue.unlink()
        cleared = postflight_opencode_run(root, run_id)
        assert cleared["status"] == "clean"
        assert cleared["environment_files_remaining"] == 0
    finally:
        resolved = root.resolve(strict=True)
        assert resolved.parent == parent.resolve(strict=True)
        shutil.rmtree(resolved)


@pytest.mark.skipif(
    os.name != "posix" or not os.environ.get("ACS_P1_DSN")
    or not os.environ.get("ACS_P1_OPENCODE_EXECUTABLE"),
    reason="actual Linux PostgreSQL/native no-model fixture is unavailable",
)
def test_actual_pg_native_capacity_prepare_and_clean_without_dispatch(tmp_path):
    import subprocess

    import psycopg

    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    key = private / "fixture-key"
    key.write_bytes(b"fixture-only")
    key.chmod(0o600)
    executable = Path(os.environ["ACS_P1_OPENCODE_EXECUTABLE"])
    with executable.open("rb") as stream:
        native_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    config = private / "opencode.json"
    config.write_text(json.dumps({
        "permission": {"*": "deny", "task": "deny"},
        "default_agent": "engineer", "model": "fixture-provider/fixture-model",
        "agent": {"engineer": {
            "model": "fixture-provider/fixture-model",
            "permission": {"*": "deny", "task": "deny"},
        }},
        "provider": {"fixture-provider": {
            "options": {"baseURL": "https://provider.example.invalid/v1"},
        }},
        "plugin": [], "mcp": {},
    }), encoding="utf-8")
    config.chmod(0o600)
    value = scene()
    value.update({
        "native_executable_path": str(executable),
        "native_executable_sha256": native_sha,
        "native_executable_size": executable.stat().st_size,
        "auth_key_ref_path": str(key),
        "auth_key_ref_path_sha256": hashlib.sha256(str(key).encode()).hexdigest(),
        "config_template_path": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    })
    scene_path = private / "scene.json"
    scene_path.write_text(json.dumps(value), encoding="utf-8")
    scene_path.chmod(0o600)
    scene_sha = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    source = Path(__file__).resolve().parents[3]
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    source_tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True
    ).strip()
    budget = private / "budget.json"
    budget.write_text(json.dumps({
        "schema_version": "acs-p1-model-request-budget/1",
        "decision_id": DECISION_ID, "source_commit": source_commit,
        "source_tree": source_tree, "scene_profile_sha256": scene_sha,
        "scenario_id": "P1-OPENCODE-LIFECYCLE",
        "provider_id": "fixture-provider", "model_id": "fixture-model",
        "prompt": MODEL_PROMPT, "max_prompt_async": 1,
        "max_collect_reads": 6, "max_elapsed_seconds": 120,
        "tool_policy": "No tool invocation or delegation.",
        "retry_policy": "No second prompt_async after uncertainty.",
        "spend_status": "Provider monetary cap not observed; cost unknown.",
    }), encoding="utf-8")
    budget.chmod(0o600)
    run_id = "p1-run-" + uuid.uuid4().hex
    schema = "p1_opencode_" + run_id.removeprefix("p1-run-")[:24]
    root = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode") / run_id
    loopback = {
        "postgres_dsn": os.environ["ACS_P1_DSN"],
        "temporal_endpoint": "127.0.0.1:7239", "temporal_namespace": "default",
        "node_id": "node-fixture",
    }
    capacity = None
    try:
        capacity = factory.prepare_opencode_host_capacity(
            loopback,
            scene_path=scene_path, scene_sha256=scene_sha,
            budget_path=budget, budget_sha256=hashlib.sha256(budget.read_bytes()).hexdigest(),
            run_id=run_id, source_commit=source_commit, source_tree=source_tree,
            machine_id="machine-fixture", node_id="node-fixture",
            source_snapshot=source, plan_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        capacity.start()
        assert capacity.ready["schema"] == schema
        assert capacity.ready["scene_sha256"] == scene_sha
        assert capacity.ready["native_sha256"] == native_sha
        proof = capacity.close()
        capacity = None
        assert proof["status"] == "clean" and proof["boot_state"] is None
    finally:
        if capacity is not None:
            capacity.close()
        if root.exists():
            factory.clean_unstarted_capacity(root, run_id, loopback["postgres_dsn"])
    with psycopg.connect(loopback["postgres_dsn"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,)
        ).fetchone()[0] == 0
    assert not root.exists()

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.runtime import p1_profile_plan as plan
from tools.runtime import p1_profile_probe as probe


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "tracked.txt").write_text("baseline\n")
    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.email", "probe@example.invalid"),
        ("git", "config", "user.name", "Probe Fixture"),
        ("git", "add", "."),
        ("git", "commit", "-qm", "baseline"),
    ):
        subprocess.run(command, cwd=root, check=True)
    return root


@pytest.fixture
def profile_file(tmp_path, source):
    if os.name != "posix":
        pytest.skip("secure loopback profile is POSIX-only")
    directory = tmp_path / "profile"
    directory.mkdir(mode=0o700)
    value = {
        "schema_version": probe.SCHEMA,
        "profile": "p1-loopback-provider",
        "source_root": str(source),
        "python": "/reviewed/python",
        "sandbox_python": "/run/acs-p1/runtime/bin/python",
        "postgres_dsn": "postgresql://acs:profile-test-only@127.0.0.1:54329/temporal",
        "temporal_endpoint": "127.0.0.1:7239",
        "temporal_namespace": "default",
        "versions": {
            "core": "0.1.0/schema-1.9",
            "provider": {"temporal": "1.32.0"},
            "database": {"postgresql": "16", "sqlite": "3"},
            "protocol": "2026-09-11.1",
            "harness": {"codex": "0.153.2", "opencode": "1.18.30"},
            "driver": {"codex": "ac4d06a", "opencode": "ac4d06a"},
            "os": {"linux": "fixture"},
        },
        "node_id": "linux-node",
        "direction": "local-bidirectional",
        "codex_model_evidence": None,
        "opencode_model_evidence": None,
    }
    path = directory / "profile.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path, value


def test_catalog_exactly_matches_formal_18_scenarios():
    contract = json.loads(
        (Path(__file__).resolve().parents[3] / "docs/runtime/gate-contract.json").read_text()
    )
    assert list(probe.ScenarioCatalog.TESTS) == contract["gates"]["P1"]["scenarios"]


@pytest.mark.skipif(os.name == "posix", reason="Windows-only fail-closed check")
def test_windows_profile_fails_closed(tmp_path):
    with pytest.raises(probe.ProbeRejected, match="absolute POSIX path"):
        probe._secure_profile(tmp_path / "profile.json")


def test_owner_only_profile_and_loopback_targets(profile_file):
    path, _value = profile_file
    loaded, digest, secrets = probe._secure_profile(path)
    assert loaded["profile"] == "p1-loopback-provider"
    assert len(digest) == 64 and secrets == (b"profile-test-only",)
    path.chmod(0o644)
    with pytest.raises(probe.ProbeRejected, match="owner-only regular"):
        probe._secure_profile(path)


@pytest.mark.parametrize("change", ["postgres_host", "postgres_port", "temporal"])
def test_non_loopback_or_wrong_provider_target_is_rejected(profile_file, change):
    path, value = profile_file
    if change == "postgres_host":
        value["postgres_dsn"] = value["postgres_dsn"].replace("127.0.0.1", "10.0.0.1")
    elif change == "postgres_port":
        value["postgres_dsn"] = value["postgres_dsn"].replace("54329", "5432")
    else:
        value["temporal_endpoint"] = "10.0.0.1:7239"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    with pytest.raises(probe.ProbeRejected, match="loopback targets"):
        probe._secure_profile(path)


def test_plan_omits_model_gaps_and_contains_no_profile_secret(profile_file):
    path, _value = profile_file
    value, status = plan.build_plan(path, sandbox_profile="/run/acs-p1/profile.json")
    assert status["available_scenarios"] == ["P1-DOMAIN-TRANSACTION"]
    assert {
        "P1-CODEX-LIFECYCLE", "P1-OPENCODE-LIFECYCLE", "P1-INTEGRATED-ACCEPTANCE",
    } < set(status["not_run"])
    for scenario, commands in value["scenarios"].items():
        if scenario in status["not_run"]:
            assert commands == []
        else:
            assert {item["kind"] for item in commands} == set(probe.KINDS)
            assert {field for item in commands for field in item["evidence_fields"]} == {
                field for fields in probe.EVIDENCE_FIELDS.values() for field in fields
            }
            assert all("/run/acs-p1/profile.json" in item["argv"] for item in commands)
    encoded = json.dumps(value)
    assert "profile-test-only" not in encoded
    assert "postgresql://" not in encoded


def test_only_current_actual_model_evidence_enables_lifecycle(profile_file, source):
    path, value = profile_file
    commit, _tree = probe._source_identity(source)
    evidence = path.parent / "opencode.json"
    evidence.write_text(json.dumps({
        "result": "pass", "source_baseline": commit, "prompt_count": 1,
        "termination": {"supervisor_proof": {"remaining_pids": []}},
    }))
    value["opencode_model_evidence"] = str(evidence)
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    loaded, _digest, _secrets = probe._secure_profile(path)
    available = probe.availability(loaded, commit)
    assert not available["P1-OPENCODE-LIFECYCLE"]["available"]
    assert "adapter" in available["P1-OPENCODE-LIFECYCLE"]["reason"]
    assert not available["P1-CODEX-LIFECYCLE"]["available"]
    assert not available["P1-INTEGRATED-ACCEPTANCE"]["available"]
    stale = json.loads(evidence.read_text())
    stale["source_baseline"] = "f" * 40
    evidence.write_text(json.dumps(stale))
    stale_status = probe.availability(loaded, commit)["P1-OPENCODE-LIFECYCLE"]
    assert not stale_status["available"] and "stale" in stale_status["reason"]


def test_runner_result_has_exact_schema_and_stable_ids(profile_file):
    _path, profile = profile_file
    profile.update({"binding_sha256": "a" * 64, "machine_id": "machine"})
    row = {
        "run_id": "run", "operation_id": "operation", "temporal_workflow_id": "workflow",
        "message_id": "message", "event_id": "event", "receipt_id": "receipt",
        "source_commit": "b" * 40, "source_tree": "c" * 40,
    }
    value = probe._runner_result(
        profile, "P1-DOMAIN-TRANSACTION", "command_output", row,
        {"command_output": True},
    )
    assert value["schema_version"] == probe.RESULT_SCHEMA and value["status"] == "passed"
    assert value["facts"]["fault_injected"] is True
    assert value["operation_ids"] == ["operation", "workflow"]


def test_missing_model_returns_not_run_before_any_output(profile_file, tmp_path):
    path, _value = profile_file
    with pytest.raises(probe.ProbeUnavailable, match="Codex"):
        probe.execute(path, "P1-CODEX-LIFECYCLE", "command_output", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_secret_scanner_rejects_profile_value_and_named_secret():
    with pytest.raises(probe.ProbeRejected, match="secret-like"):
        probe._no_secret(b"password=hunter2", ())
    with pytest.raises(probe.ProbeRejected, match="secret-like"):
        probe._no_secret(b"opaque-profile-value", (b"opaque-profile-value",))


def test_marker_only_layer_evidence_is_rejected(tmp_path, profile_file):
    _path, profile = profile_file
    ledger = probe.ProbeLedger(tmp_path / "output")
    row = {"lineage_json": "{}"}
    with pytest.raises(probe.ProbeRejected, match="marker-only"):
        probe._read_layer(
            profile, "P1-DOMAIN-TRANSACTION", "command_output", ledger, row,
        )


def test_scenario_claim_is_stable_and_pending_is_not_evidence(tmp_path):
    ledger = probe.ProbeLedger(tmp_path / "output")
    first = ledger.claim("P1-DOMAIN-TRANSACTION", "run-1")
    assert ledger.get("P1-DOMAIN-TRANSACTION") is None
    assert ledger.claim("P1-DOMAIN-TRANSACTION", "run-1") == first
    with pytest.raises(probe.ProbeRejected, match="identity changed"):
        ledger.claim("P1-DOMAIN-TRANSACTION", "run-2")


def test_output_cannot_be_formal_source(profile_file, source):
    path, _value = profile_file
    with pytest.raises(probe.ProbeRejected, match="outside source"):
        probe.execute(path, "P1-DOMAIN-TRANSACTION", "command_output", source / "gates")

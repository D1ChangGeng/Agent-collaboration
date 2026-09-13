from __future__ import annotations

import json
import os
import uuid

import pytest

from runtime.models import ArtifactRef
from tools.runtime import p1_profile_probe as probe
from tools.runtime.tests.test_p1_profile_probe_integration import _profile

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ACS_P1_PROFILE") or (
        os.environ.get("ACS_P1_DSN") and os.environ.get("ACS_P1_TEMPORAL_ENDPOINT")
    )),
    reason="real loopback PostgreSQL and Temporal profile was not provided",
)


def test_partial_artifact_same_attempt_six_layers_and_tamper_fences(
    tmp_path, monkeypatch,
):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "partial-" + uuid.uuid4().hex)
    scenario = "P1-PARTIAL-ARTIFACT"
    try:
        results = [probe.execute(profile, scenario, kind, output) for kind in probe.KINDS]
        assert len(results) == 6 and {item["status"] for item in results} == {"passed"}
        assert {item["message_ids"][0] for item in results} == {results[0]["message_ids"][0]}
        assert {item["operation_ids"][0] for item in results} == {results[0]["operation_ids"][0]}
        row = probe.ProbeLedger(output).get(scenario)
        assert row is not None
        lineage = json.loads(row["lineage_json"])
        proof = lineage["partial_artifact_proof"]
        assert proof["message_id"] == lineage["message_id"]
        assert proof["attempt_id"] == lineage["attempt_id"]
        assert proof["dispatch_id"] == lineage["dispatch_id"]
        assert proof["partial_bytes_written"] == 7
        assert proof["no_ref_issued"] and proof["temporary_files_cleaned"]
        assert proof["cleanup_directory_fsynced"]
        assert all(proof[key] for key in (
            "receipt_rejected_for_partial_cas", "finalizer_ready_rejected",
            "finalizer_accept_rejected",
        ))
        assert results[1]["facts"]["layer"]["partial_domain_zero_rows"]
        assert results[2]["facts"]["layer"]["complete_control_readback"]
        assert results[4]["facts"]["layer"]["partial_output_absent"]
        assert results[5]["facts"]["layer"]["temporary_files_absent"]

        cas_root = output / f"{scenario}-cas"
        control = ArtifactRef.model_validate(proof["control_ref"], strict=True)
        control_path = cas_root / control.path
        original = control_path.read_bytes()
        control_path.chmod(0o600)
        control_path.write_bytes(b"changed control")
        with pytest.raises(probe.ProbeRejected, match="artifact|control"):
            probe.execute(profile, scenario, "sqlite", output)
        control_path.write_bytes(original)

        proof_path = output / f"{scenario}-proof.json"
        original_proof = proof_path.read_bytes()
        proof_path.write_bytes(original_proof + b" ")
        with pytest.raises(probe.ProbeRejected, match="partial artifact proof"):
            probe.execute(profile, scenario, "driver", output)
        proof_path.write_bytes(original_proof)
    finally:
        if output.exists():
            probe.cleanup(profile, output)

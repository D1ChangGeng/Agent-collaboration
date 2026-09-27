from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from runtime.artifacts import ArtifactError, LocalArtifactStore
from runtime.models import ArtifactRef
from tools.runtime.p1_partial_artifact import (
    PartialArtifactProbeError,
    inject_partial_output,
    read_layer,
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux CAS backend")
def test_actual_partial_cas_write_cleans_temporary_file_and_issues_no_ref(tmp_path):
    with LocalArtifactStore(tmp_path / "cas", "local-scope") as store:
        control = store.put_bytes(b"complete control", kind="readback")
        observed = inject_partial_output(store, b"injected partial candidate output")
        assert observed["partial_bytes_written"] == 7
        assert observed["no_ref_issued"] and observed["temporary_files_cleaned"]
        assert observed["cleanup_directory_fsynced"]
        assert not (store.root / observed["expected_output_path"]).exists()
        assert not list(store.root.rglob(".artifact-*"))
        assert store.read(control) == b"complete control"
        unissued = ArtifactRef(
            path=observed["expected_output_path"],
            sha256=observed["expected_output_sha256"],
            size_bytes=observed["expected_output_size"],
            media_type="application/octet-stream", kind="output",
            scope_id="local-scope", immutable=True,
        )
        with pytest.raises(ArtifactError):
            store.verify(unissued)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux CAS backend")
def test_partial_artifact_readback_distinguishes_complete_and_missing_bytes(tmp_path):
    scenario = "P1-PARTIAL-ARTIFACT"
    root = tmp_path / "output"
    root.mkdir()
    with LocalArtifactStore(root / f"{scenario}-cas", "local-scope") as store:
        control = store.put_bytes(b"complete control", kind="readback")
        observed = inject_partial_output(store, b"injected partial candidate output")
    proof = {
        "message_id": "message", "delivery_operation_id": "operation",
        "attempt_id": "attempt", "dispatch_id": "dispatch",
        "machine_id": "machine", "node_id": "node",
        "source_commit": "a" * 40, "source_tree": "b" * 40,
        "control_ref": control.model_dump(mode="json"),
        "control_sha256": control.sha256,
        "receipt_rejected_for_partial_cas": True,
        "finalizer_ready_rejected": True,
        "finalizer_accept_rejected": True,
        **observed,
    }
    proof_path = root / f"{scenario}-proof.json"
    proof_bytes = json.dumps(
        proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    proof_path.write_bytes(proof_bytes)
    ledger = SimpleNamespace(root=root)
    row = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    lineage = {
        "message_id": "message", "operation_id": "operation",
        "attempt_id": "attempt", "dispatch_id": "dispatch",
        "partial_artifact_proof": proof,
    }
    profile = {"machine_id": "machine", "node_id": "node"}
    assert read_layer(profile, "sqlite", ledger, row, lineage)["complete_control_readback"]
    proof_path.write_bytes(proof_bytes + b" ")
    with pytest.raises(PartialArtifactProbeError, match="proof differs"):
        read_layer(profile, "driver", ledger, row, lineage)
    proof_path.write_bytes(proof_bytes)
    control_path = root / f"{scenario}-cas" / control.path
    control_path.chmod(0o600)
    control_path.write_bytes(b"corrupted")
    with pytest.raises(PartialArtifactProbeError, match="control artifact"):
        read_layer(profile, "os", ledger, row, lineage)

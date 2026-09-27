from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from runtime.artifacts import ArtifactError, WindowsArtifactStore
from runtime.receiver_paths import PathSecurityRejected, private_parent


def _private(path: Path) -> None:
    path.mkdir(parents=True)
    user = subprocess.run(
        ["whoami.exe"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["icacls.exe", str(path), "/inheritance:r"], check=True, capture_output=True)
    subprocess.run(
        ["icacls.exe", str(path), "/grant:r", f"{user}:(OI)(CI)F", "/T", "/C"],
        check=True, capture_output=True,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows CAS backend")
def test_windows_artifact_roundtrip_and_corruption_detection(tmp_path):
    root = tmp_path / "private-cas"
    _private(root)
    with WindowsArtifactStore(root, "scope") as store:
        ref = store.put_bytes(b"response", kind="readback", media_type="application/json")
        assert store.read(ref) == b"response"
        assert store.put_bytes(b"response", kind="readback", media_type="application/json") == ref
        (root / ref.path).write_bytes(b"changed!")
        with pytest.raises(ArtifactError):
            store.read(ref)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL backend")
def test_windows_inherited_broad_acl_is_rejected(tmp_path):
    inherited = tmp_path / "inherited"
    inherited.mkdir()
    subprocess.run(
        ["icacls.exe", str(inherited), "/grant", "*S-1-5-32-545:(OI)(CI)R"],
        check=True, capture_output=True,
    )
    with pytest.raises(PathSecurityRejected):
        private_parent(inherited)

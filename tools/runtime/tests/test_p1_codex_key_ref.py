"""Provider key-reference identity checks never read or copy key bytes."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

from tools.runtime.p1_codex_host_scene import HostSceneUncertain, _verify_key_reference


@pytest.mark.skipif(sys.platform != "linux", reason="O_PATH key reference requires Linux")
def test_empty_fixture_key_ref_mode_inode_and_link_fences():
    if os.geteuid() == 0:
        pytest.skip("non-root owner required")
    root = Path(f"/run/user/{os.geteuid()}/acs-p1-codex-key-tests")
    root.mkdir(mode=0o700, exist_ok=True)
    private = root / uuid.uuid4().hex
    private.mkdir(mode=0o700)
    key = private / "empty-ref"
    key.write_bytes(b"")
    key.chmod(0o600)
    reference = hashlib.sha256(str(key).encode()).hexdigest()
    try:
        original = _verify_key_reference(str(key), reference)
        assert len(original) == 5
        key.chmod(0o644)
        with pytest.raises(HostSceneUncertain):
            _verify_key_reference(str(key), reference)
        key.chmod(0o600)
        replacement = private / "replacement"
        replacement.write_bytes(b"")
        replacement.chmod(0o600)
        replacement.replace(key)
        assert _verify_key_reference(str(key), reference) != original
        alias = private / "alias"
        alias.symlink_to(key)
        with pytest.raises(HostSceneUncertain):
            _verify_key_reference(str(alias), hashlib.sha256(str(alias).encode()).hexdigest())
    finally:
        assert private.resolve(strict=True).parent == root.resolve(strict=True)
        shutil.rmtree(private)

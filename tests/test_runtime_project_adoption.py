from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("setup_runtime_tests", SCRIPTS / "project_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

import runtime_project_adoption as adoption


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    actions = setup.workspace_install(root, "bootstrap", False)
    assert not any(item.startswith(("error", "preserve-conflict")) for item in actions), actions
    (root / ".agents/knowledge/user.md").write_text("项目知识原文\n", encoding="utf-8")
    return root


def test_dry_run_preserves_every_byte(workspace, tmp_path):
    before = snapshot(workspace)
    backup = tmp_path / "rollback"
    result = adoption.adopt(workspace, "project-existing", dry_run=True, rollback_dir=backup)
    assert result["state"] == "planned" and len(result["changed"]) == 2
    assert snapshot(workspace) == before and not backup.exists()


def test_adoption_preserves_identity_and_guidance_then_repeats_without_writes(workspace, tmp_path):
    before = snapshot(workspace)
    original = json.loads(before[".agents/manifest.json"])
    result = adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "rollback")
    assert result["state"] == "adopted"
    after = snapshot(workspace)
    assert after["AGENTS.md"].startswith(before["AGENTS.md"])
    manifest = json.loads(after[".agents/manifest.json"])
    assert {key: manifest[key] for key in original} == original
    assert {key: value for key, value in after.items() if key not in adoption.TARGETS} == {
        key: value for key, value in before.items() if key not in adoption.TARGETS}
    assert adoption.validate(workspace)["project_id"] == "project-existing"
    again = adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "unused-backup")
    assert again["state"] == "unchanged" and not (tmp_path / "unused-backup").exists()
    assert snapshot(workspace) == after
    assert adoption.rollback(workspace, tmp_path / "rollback")["state"] == "rolled_back"
    assert snapshot(workspace) == before


def test_conflicting_identity_and_partial_markers_refuse_without_changes(workspace, tmp_path):
    adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "rollback")
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="cannot replace"):
        adoption.adopt(workspace, "project-other", rollback_dir=tmp_path / "other-backup")
    assert snapshot(workspace) == before
    with (workspace / "AGENTS.md").open("a", encoding="utf-8") as stream:
        stream.write(adoption.BEGIN)
    malformed = snapshot(workspace)
    with pytest.raises(ValueError, match="markers"):
        adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "other-backup")
    assert snapshot(workspace) == malformed


def test_mid_write_failure_restores_original_bytes(workspace, tmp_path, monkeypatch):
    before = snapshot(workspace)
    original_replace = adoption._replace
    calls = 0
    def fail_second(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-file failure")
        original_replace(path, data)
    monkeypatch.setattr(adoption, "_replace", fail_second)
    with pytest.raises(OSError, match="injected"):
        adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "rollback")
    assert snapshot(workspace) == before
    assert (tmp_path / "rollback/receipt.json").exists()


def test_rollback_refuses_to_overwrite_subsequent_user_edit(workspace, tmp_path):
    adoption.adopt(workspace, "project-existing", rollback_dir=tmp_path / "rollback")
    with (workspace / "AGENTS.md").open("a", encoding="utf-8") as stream:
        stream.write("\nNew user guidance.\n")
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="subsequent edit"):
        adoption.rollback(workspace, tmp_path / "rollback")
    assert snapshot(workspace) == before


def test_backup_inside_management_root_is_rejected(workspace):
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="outside"):
        adoption.adopt(workspace, "project-existing", rollback_dir=workspace / "backup")
    assert snapshot(workspace) == before

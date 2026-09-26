"""Opt-in Runtime project identity for an existing ACHP Management Root."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from workspace_setup import _exact_root, _safe_path, validate_workspace

BEGIN = "<!-- ACS-PROJECT:BEGIN -->"
END = "<!-- ACS-PROJECT:END -->"
SCHEMA = "acs-project-adoption/1"
TARGETS = (".agents/manifest.json", "AGENTS.md")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(root):
    result = {}
    for relative in TARGETS:
        path = _safe_path(root, relative)
        if path is None or not path.is_file():
            raise ValueError("Runtime adoption target is missing or unsafe")
        result[relative] = path.read_bytes()
    return result


def _identity(text):
    if not (text.count(BEGIN) == text.count(END) <= 1):
        raise ValueError("Runtime project markers are incomplete or duplicated")
    if BEGIN not in text:
        return None
    if text.index(BEGIN) >= text.index(END):
        raise ValueError("Runtime project marker order is invalid")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    ids = re.findall(r"^project_id: ([A-Za-z0-9._-]+)\r?$", body, re.MULTILINE)
    if len(ids) != 1:
        raise ValueError("Runtime project identity block is invalid")
    return ids[0]


def plan(root, project_id):
    root = _exact_root(Path(root), "Management Root")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", project_id):
        raise ValueError("invalid project_id")
    valid, problems = validate_workspace(root)
    if not valid:
        raise ValueError("existing Workspace requires validation: " + "; ".join(problems))
    original = _read(root)
    manifest = json.loads(original[TARGETS[0]])
    text = original[TARGETS[1]].decode("utf-8")
    presented = _identity(text)
    recorded = manifest.get("project_id")
    if recorded not in (None, project_id) or presented not in (None, project_id):
        raise ValueError("existing Project ID differs; adoption cannot replace it")
    if (recorded is None) != (presented is None):
        raise ValueError("partial Project identity requires rollback or explicit repair")
    if manifest.get("runtime_project_schema") not in (None, SCHEMA):
        raise ValueError("Runtime project schema requires an explicit migration")
    if recorded:
        if manifest.get("runtime_project_schema") != SCHEMA:
            raise ValueError("existing Project identity lacks its schema binding")
        return root, original, original.copy(), manifest["root_id"]
    newline = "\r\n" if b"\r\n" in original[TARGETS[1]] else "\n"
    block = newline.join((BEGIN, "## ACS Runtime project identity", "",
        f"project_id: {project_id}", "",
        "Use this explicit project_id for project-scoped Runtime tools.", END, ""))
    agents = original[TARGETS[1]] + (("" if text.endswith(("\n", "\r")) else newline)
                                    + newline + block).encode("utf-8")
    manifest["project_id"], manifest["runtime_project_schema"] = project_id, SCHEMA
    updated = {TARGETS[0]: (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
               TARGETS[1]: agents}
    return root, original, updated, manifest["root_id"]


def _replace(path, data):
    mode = path.stat().st_mode
    descriptor, name = tempfile.mkstemp(prefix=".acs-project-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def adopt(root, project_id, *, dry_run=False, rollback_dir=None):
    root, original, updated, root_id = plan(root, project_id)
    changed = [name for name in TARGETS if original[name] != updated[name]]
    result = {"schema_version": SCHEMA, "project_id": project_id, "root_id": root_id,
              "changed": changed, "state": "planned" if dry_run else "unchanged"}
    if dry_run or not changed:
        return result
    if rollback_dir is None:
        raise ValueError("applying Runtime adoption requires an explicit rollback directory")
    backup = _exact_root(Path(rollback_dir), "rollback directory")
    if backup == root or root in backup.parents or backup.exists():
        raise ValueError("rollback directory must be new and outside the Management Root")
    backup.mkdir(parents=True, mode=0o700)
    entries = {}
    for index, relative in enumerate(TARGETS):
        saved = backup / f"original-{index}.bin"
        saved.write_bytes(original[relative])
        saved.chmod(0o600)
        entries[relative] = {"backup": saved.name, "before_sha256": sha(original[relative]),
                             "after_sha256": sha(updated[relative])}
    receipt = {"schema_version": SCHEMA, "management_root": str(root),
               "project_id": project_id, "root_id": root_id, "files": entries}
    (backup / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    applied = []
    try:
        for relative in changed:
            target = _safe_path(root, relative)
            if target is None or target.read_bytes() != original[relative]:
                raise ValueError("adoption target changed after preview")
            _replace(target, updated[relative])
            applied.append(relative)
        validate(root, project_id)
    except BaseException:
        for relative in reversed(applied):
            target = _safe_path(root, relative)
            if target is not None and target.read_bytes() == updated[relative]:
                _replace(target, original[relative])
        raise
    return dict(result, state="adopted", rollback_dir=str(backup))


def validate(root, project_id=None):
    root = _exact_root(Path(root), "Management Root")
    original = _read(root)
    manifest = json.loads(original[TARGETS[0]])
    recorded = manifest.get("project_id")
    presented = _identity(original[TARGETS[1]].decode("utf-8"))
    if (not recorded or recorded != presented or manifest.get("runtime_project_schema") != SCHEMA
            or (project_id is not None and project_id != recorded)):
        raise ValueError("Management AGENTS and manifest Project identity differ")
    valid, problems = validate_workspace(root)
    if not valid:
        raise ValueError("Workspace validation failed: " + "; ".join(problems))
    return {"schema_version": SCHEMA, "state": "validated", "project_id": recorded,
            "root_id": manifest["root_id"]}


def rollback(root, rollback_dir):
    root = _exact_root(Path(root), "Management Root")
    backup = _exact_root(Path(rollback_dir), "rollback directory")
    receipt_path = _safe_path(backup, "receipt.json")
    if receipt_path is None:
        raise ValueError("unsafe rollback receipt")
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt.get("schema_version") != SCHEMA or receipt.get("management_root") != str(root)
            or set(receipt.get("files", {})) != set(TARGETS)):
        raise ValueError("rollback receipt belongs to another adoption")
    current = _read(root)
    originals = {}
    for relative, entry in receipt["files"].items():
        saved = _safe_path(backup, entry["backup"])
        if saved is None:
            raise ValueError("unsafe rollback file")
        originals[relative] = saved.read_bytes()
        if sha(originals[relative]) != entry["before_sha256"] or sha(current[relative]) not in {
                entry["before_sha256"], entry["after_sha256"]}:
            raise ValueError("rollback bytes conflict with a subsequent edit")
    for relative in TARGETS:
        target = _safe_path(root, relative)
        if target is None or target.read_bytes() != current[relative]:
            raise ValueError("rollback target changed during validation")
        if current[relative] != originals[relative]:
            _replace(target, originals[relative])
    return {"schema_version": SCHEMA, "state": "rolled_back", "project_id": receipt["project_id"]}

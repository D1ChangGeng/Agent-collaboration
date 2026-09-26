#!/usr/bin/env python3
"""Expose this Skill checkout to Codex, OpenCode, and/or Claude Code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SKILL_NAME = "agent-collaboration-setup"
INSTALL_MARKER = ".agent-collaboration-install.json"
_REPARSE_POINT = 0x400
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IGNORED_NAMES = {".DS_Store"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}

# Explicit published payload boundary.  Development-only state such as the
# repository's `.agents/`, `dist/`, caches, and temporary research is excluded.
# Small test fixtures may omit optional entries; real checkouts contain them.
INSTALL_CONTENT = (
    ".github",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "SKILL.md",
    "VERSION",
    "assets",
    "references",
    "scripts",
    "tests",
)
REQUIRED_CONTENT = {"SKILL.md", "VERSION", "scripts"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_reparse(path: Path) -> bool:
    """Return whether *path* is a link/junction/reparse entry.

    Inspection errors fail closed: a path that cannot be classified is not a
    safe installation source or destination.
    """
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        if os.name == "nt" and path.exists():
            attrs = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attrs & _REPARSE_POINT)
    except OSError as exc:
        raise ValueError(f"cannot inspect reparse state for {path}: {exc}") from exc
    return False


def _reject_reparse_ancestors(
    path: Path,
    label: str = "path",
    allow_final_symlink_to: Optional[Path] = None,
) -> None:
    """Reject links in a path, with an optional owned final source link."""
    current = Path(os.path.abspath(os.fspath(path.expanduser())))
    final = current
    while True:
        if _is_reparse(current):
            # An already-installed symlink that resolves exactly to this
            # checkout is a safe, idempotent destination.  Only the final
            # directory entry may use this exception; parent links and all
            # junction/reparse entries remain refused.
            if (
                current == final
                and allow_final_symlink_to is not None
                and current.is_symlink()
                and same_path(current, allow_final_symlink_to)
            ):
                pass
            else:
                raise ValueError(
                    f"{label} must not use a symlink, junction, or reparse point: {path}"
                )
        if current == current.parent:
            return
        current = current.parent


def destinations(harnesses: List[str], scope: str, project: Optional[Path]) -> List[Path]:
    hs = set(harnesses)
    if "all" in hs:
        hs = {"codex", "opencode", "claude"}

    out: List[Path] = []
    if scope == "user":
        home = Path.home()
        if {"codex", "opencode"} & hs:
            out.append(home / ".agents" / "skills" / SKILL_NAME)
        if "claude" in hs:
            out.append(home / ".claude" / "skills" / SKILL_NAME)
    else:
        if project is None:
            raise SystemExit("--project is required with --scope project")
        _reject_reparse_ancestors(project, "project destination")
        project = Path(os.path.abspath(os.fspath(project.expanduser())))
        if {"codex", "opencode"} & hs:
            out.append(project / ".agents" / "skills" / SKILL_NAME)
        if "claude" in hs:
            out.append(project / ".claude" / "skills" / SKILL_NAME)

    seen: Set[str] = set()
    unique: List[Path] = []
    for path in out:
        key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def same_location(a: Path, b: Path) -> bool:
    """Compare directory entries without following a destination link."""
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(
        os.path.abspath(os.fspath(b))
    )


def _ignored(path: Path) -> bool:
    return (
        path.name in _IGNORED_NAMES
        or path.suffix in _IGNORED_SUFFIXES
        or "__pycache__" in path.parts
    )


def _payload_entries(root: Path, require_core: bool = False) -> Tuple[Set[str], Set[str]]:
    """Return payload files/directories and reject links in allowlisted paths."""
    if not root.exists() or not root.is_dir() or _is_reparse(root):
        raise ValueError(f"Skill path is not a regular directory: {root}")

    files: Set[str] = set()
    dirs: Set[str] = set()
    for rel in INSTALL_CONTENT:
        path = root / rel
        if not path.exists():
            if require_core and rel in REQUIRED_CONTENT:
                raise ValueError(f"install payload is incomplete: {rel}")
            continue
        if _is_reparse(path):
            raise ValueError(f"Skill payload contains a symlink or reparse point: {path}")
        rel_posix = Path(rel).as_posix()
        if path.is_file():
            files.add(rel_posix)
            continue
        if not path.is_dir():
            raise ValueError(f"Skill payload entry is not regular: {path}")
        dirs.add(rel_posix)
        for child in path.rglob("*"):
            if _is_reparse(child):
                raise ValueError(
                    f"Skill payload contains a symlink or reparse point: {child}"
                )
            if _ignored(child):
                continue
            child_rel = child.relative_to(root).as_posix()
            if child.is_dir():
                dirs.add(child_rel)
            elif child.is_file():
                files.add(child_rel)
            else:
                raise ValueError(f"Skill payload entry is not regular: {child}")
    return files, dirs


def _install_files(root: Path) -> List[Path]:
    files, _dirs = _payload_entries(root)
    return sorted((root / rel for rel in files), key=lambda p: p.relative_to(root).as_posix())


def content_digest(root: Path) -> str:
    """Return a deterministic digest of the installable Skill payload."""
    digest = hashlib.sha256()
    for path in _install_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _marker_data(source: Path) -> Dict[str, str]:
    _payload_entries(source, require_core=True)
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError("install payload VERSION is empty")
    return {
        "schema_version": "1",
        "skill": SKILL_NAME,
        "source": str(source.resolve()),
        "version": version,
        "content_sha256": content_digest(source),
    }


def _read_marker(dest: Path) -> Optional[Dict[str, Any]]:
    marker = dest / INSTALL_MARKER
    if not marker.is_file() or _is_reparse(marker):
        return None
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("skill") != SKILL_NAME or value.get("schema_version") != "1":
        return None
    if not isinstance(value.get("source"), str) or not value["source"]:
        return None
    if not isinstance(value.get("version"), str) or not value["version"]:
        return None
    digest = value.get("content_sha256")
    if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
        return None
    return value


def _owned_copy(dest: Path, source: Optional[Path] = None) -> bool:
    if not dest.is_dir() or _is_reparse(dest):
        return False
    marker = _read_marker(dest)
    if marker is None:
        return False
    if source is not None:
        marker_source = os.path.normcase(os.path.abspath(str(marker["source"])))
        expected_source = os.path.normcase(os.path.abspath(os.fspath(source.resolve())))
        if marker_source != expected_source:
            return False
    return True


def _payload_matches_marker(source: Path, dest: Path) -> bool:
    marker = _read_marker(dest)
    if marker is None or not _owned_copy(dest, source):
        return False
    try:
        return marker["content_sha256"] == content_digest(dest)
    except (OSError, UnicodeError, ValueError):
        return False


def _unknown_entries(source: Path, dest: Path) -> Set[str]:
    source_files, source_dirs = _payload_entries(source, require_core=True)
    expected = source_files | source_dirs | {INSTALL_MARKER}
    unknown: Set[str] = set()
    for child in dest.rglob("*"):
        if _ignored(child):
            continue
        rel = child.relative_to(dest).as_posix()
        if rel not in expected:
            unknown.add(rel)
    return unknown


def _refuse_unowned(dest: Path) -> ValueError:
    return ValueError(
        f"refusing to replace or remove an unowned, drifted, or extended Skill destination: {dest}"
    )


def _copy_skill(source: Path, dest: Path) -> None:
    _payload_entries(source, require_core=True)
    dest.mkdir(parents=True)
    for rel in INSTALL_CONTENT:
        src = source / rel
        if not src.exists():
            continue
        target = dest / rel
        if src.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                src,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    (dest / INSTALL_MARKER).write_text(
        json.dumps(_marker_data(source), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _replace_with_staged(source: Path, dest: Path, staged: Path) -> None:
    had_destination = dest.exists() or dest.is_symlink()
    backup = dest.with_name(f".{dest.name}.backup-{uuid.uuid4().hex}")
    if had_destination:
        if dest.is_symlink() and same_path(dest, source):
            dest.rename(backup)
        else:
            if not _owned_copy(dest, source) or not _payload_matches_marker(source, dest):
                raise _refuse_unowned(dest)
            if _unknown_entries(source, dest):
                raise _refuse_unowned(dest)
            dest.rename(backup)
    try:
        staged.rename(dest)
    except Exception:
        if had_destination and backup.exists():
            backup.rename(dest)
        raise
    if had_destination:
        if _is_reparse(backup):
            backup.unlink()
        else:
            shutil.rmtree(backup)


def _remove_owned_destination(source: Path, dest: Path) -> None:
    """Remove an owned copy only when it exactly matches its recorded payload."""
    if dest.is_symlink():
        if same_path(dest, source):
            dest.unlink()
            return
        raise _refuse_unowned(dest)
    if not _owned_copy(dest, source) or not _payload_matches_marker(source, dest):
        raise _refuse_unowned(dest)
    if _unknown_entries(source, dest):
        raise _refuse_unowned(dest)
    shutil.rmtree(dest)


def install_one(source: Path, dest: Path, mode: str) -> str:
    source = source.resolve()
    _payload_entries(source, require_core=True)
    _reject_reparse_ancestors(
        dest,
        "Skill destination",
        allow_final_symlink_to=source,
    )
    if same_location(source, dest) and not dest.is_symlink():
        return "already-source"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() and same_path(dest, source):
            return "linked"
        if not _owned_copy(dest, source) or not _payload_matches_marker(source, dest):
            raise _refuse_unowned(dest)
        if _unknown_entries(source, dest):
            raise _refuse_unowned(dest)

    staged = dest.with_name(f".{dest.name}.staging-{uuid.uuid4().hex}")
    if mode in {"auto", "symlink"}:
        try:
            staged.symlink_to(source, target_is_directory=True)
        except OSError:
            if mode == "symlink":
                raise
        else:
            try:
                _replace_with_staged(source, dest, staged)
            except Exception:
                if staged.is_symlink() or staged.exists():
                    staged.unlink()
                raise
            return "linked"

    try:
        _copy_skill(source, staged)
        _replace_with_staged(source, dest, staged)
    except Exception:
        if staged.is_symlink():
            staged.unlink()
        elif staged.exists():
            shutil.rmtree(staged)
        raise
    return "copied"


def check_one(source: Path, dest: Path) -> Tuple[bool, str]:
    if not dest.exists() and not dest.is_symlink():
        return False, "missing"
    if dest.is_symlink():
        return same_path(dest, source), f"symlink -> {dest.resolve()}"
    if not (dest / "SKILL.md").exists():
        return False, "SKILL.md missing"
    marker = _read_marker(dest)
    if marker is None:
        return False, "unowned or legacy copy; installation marker missing/invalid"
    if not _owned_copy(dest, source):
        return False, "copy ownership marker source mismatch"
    try:
        expected = content_digest(source)
        actual = content_digest(dest)
    except (OSError, UnicodeError, ValueError) as exc:
        return False, f"copy check refused: {exc}"
    ok = marker["content_sha256"] == expected == actual
    return ok, f"copy digest={'match' if ok else 'mismatch'}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", nargs="+", default=["all"], choices=["all", "codex", "opencode", "claude"])
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--mode", choices=["auto", "symlink", "copy"], default="auto")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.check and args.uninstall:
        parser.error("--check and --uninstall cannot be combined")

    source = repo_root()
    dests = destinations(args.harness, args.scope, args.project)
    if args.check:
        failed = False
        for dest in dests:
            try:
                ok, detail = check_one(source, dest)
            except (OSError, UnicodeError, ValueError) as exc:
                ok, detail = False, f"check refused: {exc}"
            print(f"[{'OK' if ok else 'FAIL'}] {dest}: {detail}")
            failed = failed or not ok
        return 1 if failed else 0

    if args.uninstall:
        failed = False
        for dest in dests:
            if same_location(source, dest) and not dest.is_symlink():
                print(f"[SKIP] {dest}: this is the source checkout")
                continue
            if dest.exists() or dest.is_symlink():
                try:
                    _remove_owned_destination(source, dest)
                    print(f"[REMOVED] {dest}")
                except (OSError, UnicodeError, ValueError) as exc:
                    print(f"[REFUSED] {exc}")
                    failed = True
            else:
                print(f"[ABSENT] {dest}")
        return 1 if failed else 0

    failed = False
    for dest in dests:
        try:
            result = install_one(source, dest, args.mode)
            print(f"[{result.upper()}] {dest}")
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"[REFUSED] {exc}")
            failed = True
    if failed:
        return 1
    print("Installation complete. Restart/reload the harness only if it does not detect the Skill immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

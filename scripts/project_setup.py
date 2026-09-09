#!/usr/bin/env python3
"""Install/maintain ACHP project scaffolding without becoming a runtime dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

# Workspace/Route operations live in a separate module so the legacy
# repository-oriented API remains stable.  Keep the sibling import available
# both when this file is executed as a script and when tests load it by path.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    from workspace_setup import (  # type: ignore
        main as workspace_cli_main,
        read_json as workspace_read_json,
        route_operation as workspace_route_operation,
        validate_workspace as workspace_validate,
        workspace_install,
    )
    # Compatibility exports used by the existing test/API surface.
    validate_workspace = workspace_validate
    read_json = workspace_read_json
except ImportError:
    workspace_cli_main = None
    workspace_read_json = None
    workspace_route_operation = None
    workspace_validate = None
    workspace_install = None
    validate_workspace = None
    route_operation = None
    read_json = None


def route_operation(args):
    """Compatibility wrapper for the workspace Route API."""
    if workspace_route_operation is None:
        raise RuntimeError("workspace/route support is unavailable")
    return workspace_route_operation(args, Path(__file__).resolve().parents[1] / "assets" / "scaffold")

VERSION = "0.4.0"
AGENTS_BEGIN = "<!-- ACHP:BEGIN -->"
AGENTS_END = "<!-- ACHP:END -->"
CLAUDE_BEGIN = "<!-- ACHP-CLAUDE-ROUTER:BEGIN -->"
CLAUDE_END = "<!-- ACHP-CLAUDE-ROUTER:END -->"
GITIGNORE_BEGIN = "# ACHP:BEGIN"
GITIGNORE_END = "# ACHP:END"

MANAGED_FILES = [
    ".agents/README.md",
    ".agents/protocol/CAPABILITIES.md",
    ".agents/protocol/RELAY.md",
    ".agents/protocol/GIT-SYNC.md",
    ".agents/protocol/KNOWLEDGE.md",
    ".agents/coordination/roles/coordinator.md",
    ".agents/coordination/roles/executor.md",
    ".agents/coordination/roles/reviewer.md",
    ".agents/coordination/templates/TASK.md",
    ".agents/coordination/templates/HANDOFF.md",
    ".agents/coordination/templates/RELAY.txt",
    ".agents/knowledge/README.md",
]

CREATE_IF_MISSING = [
    ".agents/config.yaml",
    ".agents/coordination/PROJECT.md",
    ".agents/coordination/tasks/.gitkeep",
    ".agents/coordination/handoffs/.gitkeep",
    ".agents/knowledge/guides/.gitkeep",
    ".agents/knowledge/decisions/.gitkeep",
    ".agents/knowledge/observations/.gitkeep",
    ".agents/knowledge/archive/.gitkeep",
]

# Repository-level managed instruction blocks are kept separate from the
# scaffold asset list.  The surrounding file may be project-owned, while the
# marked block is setup-owned and can therefore be checked independently.
MANAGED_BLOCKS = {
    "AGENTS.md": (AGENTS_BEGIN, AGENTS_END, "AGENTS_BLOCK.md"),
    "CLAUDE.md": (CLAUDE_BEGIN, CLAUDE_END, "CLAUDE_BLOCK.md"),
    ".gitignore": (GITIGNORE_BEGIN, GITIGNORE_END, "GITIGNORE_BLOCK.txt"),
}

MANIFEST_REL = ".agents/manifest.json"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def scaffold_root() -> Path:
    return skill_root() / "assets" / "scaffold"


def read_asset(rel: str) -> str:
    return (scaffold_root() / rel).read_text(encoding="utf-8")


def _is_reparse_point(path: Path) -> bool:
    """Detect symlink/junction/reparse entries without following them."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        if os.name == "nt" and path.exists():
            attrs = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError as exc:
        raise ValueError(f"cannot inspect reparse state for {path}: {exc}") from exc
    return False


def _reject_alias_path(path: Path, label: str = "repository target") -> None:
    """Reject a supplied path that would redirect writes through a reparse point."""
    current = Path(os.path.abspath(os.fspath(path.expanduser())))
    while True:
        if _is_reparse_point(current):
            raise ValueError(f"{label} must not use a symlink, junction, or reparse point: {path}")
        if current == current.parent:
            break
        current = current.parent


def find_repo_root(start: Path, use_git_root: bool = False) -> Path:
    """Resolve the supplied target exactly unless Git-root discovery is explicit."""
    _reject_alias_path(start)
    start = Path(os.path.abspath(os.fspath(start)))
    if not use_git_root:
        return start
    if not start.is_dir():
        raise ValueError(f"cannot discover Git root from a non-directory: {start}")
    try:
        cp = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("Git is unavailable; --git-root cannot be resolved") from exc
    if cp.returncode != 0 or not cp.stdout.strip():
        detail = cp.stderr.strip() or "the supplied path is not inside a Git work tree"
        raise ValueError(f"cannot resolve --git-root: {detail}")
    return Path(cp.stdout.strip()).resolve()


def replace_block(text: str, begin: str, end: str, block: str) -> str:
    validate_marker_pair(text, begin, end, "managed file")
    block = block.strip() + "\n"
    if begin in text and end in text:
        left, rest = text.split(begin, 1)
        _, right = rest.split(end, 1)
        new = left.rstrip() + ("\n\n" if left.strip() else "") + block
        if right.strip():
            new += "\n" + right.lstrip()
        return new
    if text.strip():
        return text.rstrip() + "\n\n" + block
    return block


def extract_block(text: str, begin: str, end: str) -> Optional[str]:
    """Return the complete validated managed block, or None when absent."""
    validate_marker_pair(text, begin, end, "managed file")
    if begin not in text:
        return None
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return begin + body + end


def normalized_text_digest(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalized_file_digest(path: Path) -> str:
    return normalized_text_digest(path.read_text(encoding="utf-8"))


def expected_block(filename: str) -> str:
    begin, end, asset = MANAGED_BLOCKS[filename]
    return extract_block(read_asset(asset), begin, end) or ""


def block_digest(text: str, filename: str) -> Optional[str]:
    begin, end, _asset = MANAGED_BLOCKS[filename]
    block = extract_block(text, begin, end)
    return normalized_text_digest(block) if block is not None else None


def expected_block_digest(filename: str) -> str:
    return normalized_text_digest(expected_block(filename))


def validate_marker_pair(text: str, begin: str, end: str, label: str) -> None:
    """Require a managed block to be absent or exactly one well-ordered pair."""
    begin_count = text.count(begin)
    end_count = text.count(end)
    if (begin_count, end_count) == (0, 0):
        return
    if (begin_count, end_count) != (1, 1):
        raise ValueError(
            f"{label} managed block markers must occur as 0/0 or 1/1 "
            f"(found {begin_count}/{end_count})"
        )
    if text.index(begin) >= text.index(end):
        raise ValueError(f"{label} managed block begin marker must precede end marker")


def validate_existing_managed_blocks(root: Path) -> None:
    """Validate all existing managed files before any setup write occurs."""
    for filename, begin, end in (
        ("AGENTS.md", AGENTS_BEGIN, AGENTS_END),
        ("CLAUDE.md", CLAUDE_BEGIN, CLAUDE_END),
        (".gitignore", GITIGNORE_BEGIN, GITIGNORE_END),
    ):
        path = root / filename
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError(f"managed target must not be a symlink: {path}")
        if not path.is_file():
            raise ValueError(f"managed target is not a file: {path}")
        validate_marker_pair(path.read_text(encoding="utf-8"), begin, end, filename)


def remove_block(text: str, begin: str, end: str) -> str:
    if begin not in text or end not in text:
        return text
    left, rest = text.split(begin, 1)
    _, right = rest.split(end, 1)
    return (left.rstrip() + ("\n\n" if left.strip() and right.strip() else "") + right.lstrip()).rstrip() + ("\n" if (left.strip() or right.strip()) else "")


def write_text(path: Path, content: str, dry_run: bool, actions: list[str]) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    actions.append(f"write {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside the target and atomically replace it.  This avoids a
        # truncated managed file if a write is interrupted; prior content
        # remains available until the final replace succeeds.
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def copy_asset(rel: str, target: Path, dry_run: bool, actions: list[str], overwrite: bool) -> None:
    src = scaffold_root() / rel
    dst = target / rel
    if dst.exists() and not overwrite:
        return
    content = src.read_text(encoding="utf-8")
    write_text(dst, content, dry_run, actions)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def read_repository_manifest(root: Path, *, required: bool = False) -> dict:
    path = root / MANIFEST_REL
    if not path.exists():
        if required:
            raise ValueError(
                f"repository manifest missing: {path}; repair/upgrade requires an existing ACHP setup"
            )
        return {}
    if not path.is_file():
        raise ValueError(f"repository manifest is not a file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"repository manifest invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("repository manifest must be a JSON object")
    if value.get("protocol") != "ACHP":
        raise ValueError("repository manifest protocol is not ACHP")
    if value.get("setup_skill") not in (None, "agent-collaboration-setup"):
        raise ValueError("repository manifest setup_skill is invalid")
    if value.get("runtime_dependency_on_setup_skill") is not False:
        raise ValueError("repository manifest runtime dependency boundary invalid")
    for key in ("managed_files", "project_owned_files"):
        items = value.get(key)
        if items is not None and (
            not isinstance(items, list) or not all(isinstance(item, str) for item in items)
        ):
            raise ValueError(f"repository manifest {key} must be a list of strings")
    hashes = value.get("managed_hashes")
    if hashes is not None and (
        not isinstance(hashes, dict)
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in hashes.items())
    ):
        raise ValueError("repository manifest managed_hashes must map paths to digests")
    block_hashes = value.get("managed_block_hashes")
    if block_hashes is not None and (
        not isinstance(block_hashes, dict)
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in block_hashes.items())
    ):
        raise ValueError("repository manifest managed_block_hashes must map paths to digests")
    return value


def _manifest_owned_files(manifest: dict) -> set[str]:
    value = manifest.get("managed_files", [])
    return {item for item in value if isinstance(item, str)}


def _manifest_hashes(manifest: dict, field: str) -> dict[str, str]:
    value = manifest.get(field, {})
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _asset_is_owned_for_upgrade(root: Path, manifest: dict, rel: str) -> bool:
    """Return whether an existing managed asset has unambiguous setup ownership."""
    path = _safe_repository_path(root, rel)
    if not path.exists():
        return True
    if not path.is_file():
        raise ValueError(f"repository setup target is not a file: {path}")
    scaffold = scaffold_root() / rel
    if path.read_bytes() == scaffold.read_bytes():
        return True
    recorded = _manifest_hashes(manifest, "managed_hashes").get(rel)
    return bool(recorded and recorded == sha256(path))


def _block_is_owned_for_upgrade(root: Path, manifest: dict, filename: str) -> bool:
    """Return whether an existing marked block can be safely refreshed."""
    path = root / filename
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    begin, end, _asset = MANAGED_BLOCKS[filename]
    if begin not in text and end not in text:
        return True
    digest = block_digest(text, filename)
    if digest is None:
        return False
    if digest == expected_block_digest(filename):
        return True
    recorded = _manifest_hashes(manifest, "managed_block_hashes").get(filename)
    return bool(recorded and recorded == digest)


def _managed_asset_state(root: Path, manifest: dict, rel: str) -> str:
    """Classify a managed asset without mutating it."""
    path = root / rel
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "conflict"
    current = normalized_file_digest(path)
    expected = normalized_file_digest(scaffold_root() / rel)
    if current == expected:
        return "current"
    recorded = _manifest_hashes(manifest, "managed_hashes").get(rel)
    if recorded and recorded in {sha256(path), current}:
        return "recorded-legacy"
    return "drift"


def _managed_block_state(root: Path, manifest: dict, filename: str) -> str:
    path = root / filename
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "conflict"
    text = path.read_text(encoding="utf-8")
    digest = block_digest(text, filename)
    if digest is None:
        return "missing"
    if digest == expected_block_digest(filename):
        return "current"
    recorded = _manifest_hashes(manifest, "managed_block_hashes").get(filename)
    if recorded and recorded == digest:
        return "recorded-legacy"
    # v0.1-v0.3 repository manifests did not carry a block ledger.  Preserve
    # their well-formed existing block during adopt/repair and require an
    # explicit upgrade to refresh it.
    if manifest and "managed_block_hashes" not in manifest:
        return "unbound-legacy"
    return "drift"


def _target_state(root: Path) -> str:
    """Return missing, empty, or populated for repository lifecycle checks."""
    if not root.exists():
        return "missing"
    if not root.is_dir():
        return "invalid"
    try:
        return "empty" if not any(root.iterdir()) else "populated"
    except OSError as exc:
        raise ValueError(f"cannot inspect repository target {root}: {exc}") from exc


def _safe_repository_path(root: Path, rel: str, *, require_file: bool = False) -> Path:
    """Resolve a repository-relative path while rejecting symlink escapes."""
    candidate = root / rel
    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"repository setup path is unsafe: {rel}")
    # Check every existing ancestor, not only the final entry.  A symlinked
    # `.agents/` directory would otherwise redirect writes outside the target.
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"repository setup path contains a symlink: {rel}")
        if current != candidate and current.exists() and not current.is_dir():
            raise ValueError(f"repository setup parent is not a directory: {current}")
    if candidate.exists() and candidate.is_symlink():
        raise ValueError(f"repository setup path is a symlink: {rel}")
    if require_file and candidate.exists() and not candidate.is_file():
        raise ValueError(f"repository setup target is not a file: {candidate}")
    return candidate


def _planned_block(root: Path, filename: str, mode: str) -> str:
    begin, end, asset = MANAGED_BLOCKS[filename]
    path = _safe_repository_path(root, filename)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    validate_marker_pair(existing, begin, end, filename)
    if mode in {"adopt", "repair"} and path.exists() and begin not in existing:
        if mode == "repair":
            raise ValueError(
                f"repair cannot establish ownership of an unmarked managed file: {path}; use adopt"
            )
        # Adopt adds the block while preserving the surrounding project text.
    if mode in {"adopt", "repair"} and begin in existing and end in existing:
        return existing
    return replace_block(existing, begin, end, read_asset(asset))


def _planned_asset(root: Path, rel: str, mode: str) -> bytes:
    path = _safe_repository_path(root, rel)
    if path.exists() and mode in {"adopt", "repair"}:
        return path.read_bytes()
    return (scaffold_root() / rel).read_bytes()


def _ensure_upgrade_ownership(root: Path, manifest: dict) -> None:
    """Refuse to overwrite existing managed content without ownership proof."""
    for rel in MANAGED_FILES:
        path = _safe_repository_path(root, rel)
        if path.exists() and not _asset_is_owned_for_upgrade(root, manifest, rel):
            raise ValueError(
                f"managed asset ownership is unverified; upgrade refused: {path}"
            )
    for filename in MANAGED_BLOCKS:
        path = root / filename
        if path.exists() and not _block_is_owned_for_upgrade(root, manifest, filename):
            raise ValueError(
                f"managed block ownership is unverified; upgrade refused: {path}"
            )


def _repository_manifest(
    root: Path,
    old: dict,
    mode: str,
    planned: Optional[Dict[str, bytes]] = None,
    planned_blocks: Optional[Dict[str, str]] = None,
) -> dict:
    """Build setup ownership metadata, never runtime progress state."""
    data = {
        "protocol": "ACHP",
        "version": VERSION,
        "setup_skill": "agent-collaboration-setup",
        "managed_files": list(MANAGED_FILES),
        "project_owned_files": list(CREATE_IF_MISSING),
        "runtime_dependency_on_setup_skill": False,
    }
    known = set(data) | {"managed_hashes", "managed_block_hashes"}
    for key, value in old.items():
        if key not in known:
            data[key] = value

    previous_hashes = _manifest_hashes(old, "managed_hashes")
    previous_block_hashes = _manifest_hashes(old, "managed_block_hashes")
    planned = planned or {}
    planned_blocks = planned_blocks or {}

    managed_hashes: dict[str, str] = {}
    for rel in MANAGED_FILES:
        path = _safe_repository_path(root, rel)
        existed_before = path.exists()
        if rel in planned:
            content = planned[rel]
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        if mode in {"adopt", "repair"} and rel in previous_hashes and existed_before:
            # Keep the prior baseline so validate reports a project edit as
            # drift instead of silently re-baselining it during adopt/repair.
            managed_hashes[rel] = previous_hashes[rel]
        elif (
            mode in {"adopt", "repair"}
            and existed_before
            and content != (scaffold_root() / rel).read_bytes()
        ):
            # An existing non-scaffold file with no prior ownership proof is
            # project content, not evidence that setup owns the path.  Do not
            # mint a fresh hash during adopt/repair: otherwise a later
            # explicit upgrade could mistake the adopted bytes for a managed
            # baseline and overwrite them.
            continue
        else:
            managed_hashes[rel] = hashlib.sha256(content).hexdigest()

    block_hashes: dict[str, str] = {}
    for filename in MANAGED_BLOCKS:
        path = _safe_repository_path(root, filename)
        existed_before = path.is_file()
        existing_digest: Optional[str] = None
        if existed_before:
            existing_digest = block_digest(
                path.read_text(encoding="utf-8"), filename
            )
        if filename in planned_blocks:
            text = planned_blocks[filename]
        elif path.is_file():
            text = path.read_text(encoding="utf-8")
        else:
            continue
        digest = block_digest(text, filename)
        if digest is None:
            continue
        if (
            mode in {"adopt", "repair"}
            and filename in previous_block_hashes
            and existed_before
        ):
            block_hashes[filename] = previous_block_hashes[filename]
        elif (
            mode in {"adopt", "repair"}
            and existed_before
            and existing_digest is not None
            and existing_digest != expected_block_digest(filename)
        ):
            # A pre-existing marked block whose body differs from the current
            # scaffold is project content unless an earlier manifest already
            # proved setup ownership.  Do not mint a new ownership baseline
            # during adopt/repair; a later explicit upgrade must ask for
            # review instead of treating the adopted block as replaceable.
            continue
        else:
            block_hashes[filename] = digest
    data["managed_hashes"] = managed_hashes
    data["managed_block_hashes"] = block_hashes
    return data


def _record_plan(
    root: Path,
    rel: str,
    content: Union[bytes, str],
    actions: List[str],
    planned: Dict[str, bytes],
    planned_blocks: Optional[Dict[str, str]] = None,
) -> None:
    path = _safe_repository_path(root, rel)
    if isinstance(content, str):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if content != current:
            actions.append(f"write {path}")
        if planned_blocks is not None:
            planned_blocks[rel] = content
        return
    current_bytes = path.read_bytes() if path.exists() else None
    if current_bytes != content:
        actions.append(f"write {path}")
    planned[rel] = content


def install_or_upgrade(root: Path, mode: str, dry_run: bool) -> list[str]:
    """Apply a conservative, explicit repository lifecycle operation."""
    supplied = Path(root).expanduser()
    _reject_alias_path(supplied)
    if supplied.is_symlink():
        raise ValueError(f"repository target must not be a symlink: {supplied}")
    root = supplied.resolve()
    actions: List[str] = []
    if mode not in {"bootstrap", "adopt", "upgrade", "repair"}:
        raise ValueError(f"unsupported repository setup mode: {mode}")
    state = _target_state(root)
    if state == "invalid":
        raise ValueError(f"repository target is not a directory: {root}")
    if mode == "bootstrap" and state == "populated":
        raise ValueError(
            "bootstrap requires a missing or empty repository target; use adopt for existing content"
        )
    if mode in {"upgrade", "repair"} and state != "populated":
        raise ValueError(f"{mode} requires an existing ACHP repository setup")

    manifest_path = _safe_repository_path(root, MANIFEST_REL)
    old: dict = {}
    if manifest_path.exists():
        old = read_repository_manifest(root, required=True)
    elif mode in {"upgrade", "repair"}:
        raise ValueError(
            f"repository manifest missing: {manifest_path}; {mode} requires an existing ACHP setup"
        )

    validate_existing_managed_blocks(root)
    if mode == "upgrade":
        _ensure_upgrade_ownership(root, old)
    for rel in MANAGED_FILES + CREATE_IF_MISSING:
        _safe_repository_path(root, rel, require_file=True)

    planned: Dict[str, bytes] = {}
    planned_blocks: Dict[str, str] = {}
    for filename in MANAGED_BLOCKS:
        _record_plan(root, filename, _planned_block(root, filename, mode), actions, planned, planned_blocks)
    for rel in MANAGED_FILES:
        path = _safe_repository_path(root, rel)
        if path.exists() and mode in {"adopt", "repair"}:
            planned[rel] = path.read_bytes()
            continue
        _record_plan(root, rel, _planned_asset(root, rel, mode), actions, planned)
    for rel in CREATE_IF_MISSING:
        path = _safe_repository_path(root, rel)
        if path.exists():
            planned[rel] = path.read_bytes()
            continue
        _record_plan(root, rel, _planned_asset(root, rel, mode), actions, planned)

    manifest = _repository_manifest(root, old, mode, planned, planned_blocks)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    current_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if manifest_text != current_manifest:
        actions.append(f"write {manifest_path}")

    if dry_run:
        return actions

    root.mkdir(parents=True, exist_ok=True)
    for filename, content in planned_blocks.items():
        write_text(_safe_repository_path(root, filename), content, False, [])
    for rel, content in planned.items():
        # The block paths are represented separately and must not be interpreted
        # as byte assets here.
        if rel in MANAGED_BLOCKS:
            continue
        path = _safe_repository_path(root, rel)
        if rel in MANAGED_FILES and path.exists() and mode in {"adopt", "repair"}:
            continue
        write_text(path, content.decode("utf-8"), False, [])
    write_text(manifest_path, manifest_text, False, [])
    return actions


def validate(root: Path) -> tuple[bool, list[str]]:
    supplied = Path(root).expanduser()
    try:
        _reject_alias_path(supplied)
    except ValueError as exc:
        return False, [str(exc)]
    if supplied.is_symlink():
        return False, [f"repository target must not be a symlink: {supplied}"]
    root = supplied.resolve()
    if not root.exists():
        return False, [f"repository target missing: {root}"]
    if not root.is_dir():
        return False, [f"repository target is not a directory: {root}"]
    problems: List[str] = []
    try:
        validate_existing_managed_blocks(root)
    except (OSError, ValueError) as exc:
        problems.append(f"managed block markers invalid: {exc}")

    manifest: dict = {}
    try:
        manifest = read_repository_manifest(root, required=True)
    except (OSError, ValueError) as exc:
        problems.append(str(exc))

    for rel in MANAGED_FILES + CREATE_IF_MISSING + [MANIFEST_REL]:
        try:
            path = _safe_repository_path(root, rel)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if path.is_symlink():
            problems.append(f"symlink is not an owned repository setup file: {rel}")
        elif not path.exists():
            problems.append(f"missing {rel}")
        elif not path.is_file():
            problems.append(f"repository setup target is not a file: {rel}")

    for filename, (begin, end, missing_message) in {
        "AGENTS.md": (AGENTS_BEGIN, AGENTS_END, "AGENTS.md ACHP managed block missing/incomplete"),
        "CLAUDE.md": (CLAUDE_BEGIN, CLAUDE_END, "CLAUDE.md ACHP router missing/incomplete"),
        ".gitignore": (GITIGNORE_BEGIN, GITIGNORE_END, ".gitignore ACHP runtime block missing"),
    }.items():
        path = root / filename
        if not path.exists():
            problems.append(f"{filename} missing")
            continue
        if path.is_symlink() or not path.is_file():
            problems.append(f"{filename} is not a regular file")
            continue
        text = path.read_text(encoding="utf-8")
        if begin not in text or end not in text:
            problems.append(missing_message)
        if filename == "AGENTS.md" and "agent-collaboration-setup" not in text:
            problems.append("AGENTS.md setup/runtime boundary text missing")
        if filename == "CLAUDE.md" and "@AGENTS.md" not in text:
            problems.append("CLAUDE.md ACHP router missing/incomplete")

    for rel, expected in _manifest_hashes(manifest, "managed_hashes").items():
        try:
            path = _safe_repository_path(root, rel)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if path.is_file() and not path.is_symlink() and sha256(path) != expected:
            problems.append(f"managed asset drift: {rel}")

    for filename, expected in _manifest_hashes(manifest, "managed_block_hashes").items():
        if filename not in MANAGED_BLOCKS:
            problems.append(f"manifest contains unknown managed block: {filename}")
            continue
        path = root / filename
        if not path.is_file() or path.is_symlink():
            continue
        try:
            actual = block_digest(path.read_text(encoding="utf-8"), filename)
        except (OSError, ValueError):
            continue
        if actual != expected:
            problems.append(f"managed block drift: {filename}")

    if manifest and str(manifest.get("version", "")) == VERSION:
        listed = _manifest_owned_files(manifest)
        missing_inventory = [rel for rel in MANAGED_FILES if rel not in listed]
        if missing_inventory:
            problems.append(
                "manifest managed_files inventory incomplete: " + ", ".join(missing_inventory)
            )
    return not problems, problems


def uninstall(root: Path, dry_run: bool, purge_data: bool) -> list[str]:
    supplied = Path(root).expanduser()
    _reject_alias_path(supplied)
    if supplied.is_symlink():
        raise ValueError(f"repository target must not be a symlink: {supplied}")
    root = supplied.resolve()
    manifest = read_repository_manifest(root, required=True)
    managed_hashes = _manifest_hashes(manifest, "managed_hashes")
    if set(MANAGED_FILES) - set(managed_hashes):
        raise ValueError(
            "repository uninstall requires ownership hashes for every managed file"
        )
    for rel in MANAGED_FILES:
        path = _safe_repository_path(root, rel)
        if not path.is_file() or sha256(path) != managed_hashes[rel]:
            raise ValueError(f"repository uninstall ownership check failed: {rel}")
    block_hashes = _manifest_hashes(manifest, "managed_block_hashes")
    if set(MANAGED_BLOCKS) - set(block_hashes):
        raise ValueError(
            "repository uninstall requires ownership hashes for all managed blocks"
        )
    for filename in MANAGED_BLOCKS:
        path = root / filename
        if not path.is_file():
            raise ValueError(f"repository uninstall managed block is missing: {filename}")
        actual = block_digest(path.read_text(encoding="utf-8"), filename)
        if actual != block_hashes[filename]:
            raise ValueError(f"repository uninstall ownership check failed: {filename}")

    actions: List[str] = []
    validate_existing_managed_blocks(root)

    for filename, begin, end in [
        ("AGENTS.md", AGENTS_BEGIN, AGENTS_END),
        ("CLAUDE.md", CLAUDE_BEGIN, CLAUDE_END),
        (".gitignore", GITIGNORE_BEGIN, GITIGNORE_END),
    ]:
        p = root / filename
        if p.exists():
            old = p.read_text(encoding="utf-8")
            new = remove_block(old, begin, end)
            if new != old:
                if new.strip():
                    write_text(p, new, dry_run, actions)
                else:
                    actions.append(f"remove {p}")
                    if not dry_run:
                        p.unlink()

    # Only known setup-managed files.
    for rel in MANAGED_FILES:
        p = root / rel
        if p.exists() or p.is_symlink():
            actions.append(f"remove {p}")
            if not dry_run:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()

    manifest_path = root / MANIFEST_REL
    if manifest_path.exists():
        actions.append(f"remove {manifest_path}")
        if not dry_run:
            manifest_path.unlink()

    if purge_data:
        agents_dir = root / ".agents"
        if agents_dir.exists():
            actions.append(f"purge {agents_dir}")
            if not dry_run:
                shutil.rmtree(agents_dir)
    else:
        # Clean only empty setup-owned dirs, preserve project data.
        if not dry_run:
            for rel in [
                ".agents/protocol",
                ".agents/coordination/roles",
                ".agents/coordination/templates",
            ]:
                p = root / rel
                try:
                    p.rmdir()
                except OSError:
                    pass

    return actions


def print_git_summary(root: Path) -> None:
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            check=False,
        )
        if cp.returncode == 0:
            print("\nGit status:")
            print(cp.stdout.rstrip() or "(clean)")
    except FileNotFoundError:
        pass


def main() -> int:
    # Explicit Workspace/Route commands use the new exact-path control plane.
    # Legacy repository commands below remain unchanged.
    if len(sys.argv) > 1 and sys.argv[1] in {"workspace", "route"}:
        if workspace_cli_main is None:
            print("[FAIL] workspace/route support is unavailable")
            return 1
        return workspace_cli_main(sys.argv[1:])
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["bootstrap", "adopt", "upgrade", "repair", "validate", "uninstall"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--git-root",
        action="store_true",
        help="explicitly resolve --root to its containing Git work-tree root",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-data", action="store_true")
    args = parser.parse_args()

    try:
        root = find_repo_root(args.root, use_git_root=args.git_root)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"Repository target: {root}")

    if args.mode == "validate":
        ok, problems = validate(root)
        if ok:
            print(f"[OK] ACHP {VERSION} setup is structurally valid.")
            print_git_summary(root)
            return 0
        print("[FAIL] ACHP setup validation failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if args.mode == "uninstall":
        try:
            actions = uninstall(root, args.dry_run, args.purge_data)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] {exc}")
            return 1
    else:
        try:
            actions = install_or_upgrade(root, args.mode, args.dry_run)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] {exc}")
            return 1

    prefix = "[DRY-RUN]" if args.dry_run else "[APPLIED]"
    if actions:
        for action in actions:
            print(f"{prefix} {action}")
    else:
        print(f"{prefix} no changes required")

    if not args.dry_run and args.mode != "uninstall":
        ok, problems = validate(root)
        if not ok:
            print("[FAIL] post-install validation failed:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(f"[OK] ACHP {VERSION} setup validated.")

    print_git_summary(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

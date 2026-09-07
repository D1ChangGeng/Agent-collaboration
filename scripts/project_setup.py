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
from pathlib import Path

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

VERSION = "0.3.0"
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


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def scaffold_root() -> Path:
    return skill_root() / "assets" / "scaffold"


def read_asset(rel: str) -> str:
    return (scaffold_root() / rel).read_text(encoding="utf-8")


def find_repo_root(start: Path) -> Path:
    start = start.resolve()
    try:
        cp = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            return Path(cp.stdout.strip()).resolve()
    except FileNotFoundError:
        pass
    return start


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
        path.write_text(content, encoding="utf-8")


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


def install_or_upgrade(root: Path, mode: str, dry_run: bool) -> list[str]:
    actions: list[str] = []
    validate_existing_managed_blocks(root)

    # Managed AGENTS block.
    agents_path = root / "AGENTS.md"
    existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_block = read_asset("AGENTS_BLOCK.md")
    write_text(
        agents_path,
        replace_block(existing, AGENTS_BEGIN, AGENTS_END, agents_block),
        dry_run,
        actions,
    )

    # Thin Claude Code router only.
    claude_path = root / "CLAUDE.md"
    existing = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
    claude_block = read_asset("CLAUDE_BLOCK.md")
    write_text(
        claude_path,
        replace_block(existing, CLAUDE_BEGIN, CLAUDE_END, claude_block),
        dry_run,
        actions,
    )

    # Runtime ignore block.
    gi_path = root / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""
    gi_block = read_asset("GITIGNORE_BLOCK.txt")
    write_text(
        gi_path,
        replace_block(existing, GITIGNORE_BEGIN, GITIGNORE_END, gi_block),
        dry_run,
        actions,
    )

    # Stable managed protocol/template files.
    for rel in MANAGED_FILES:
        copy_asset(rel, root, dry_run, actions, overwrite=True)

    # Project-owned files/directories: initialize only.
    for rel in CREATE_IF_MISSING:
        copy_asset(rel, root, dry_run, actions, overwrite=False)

    # The repository manifest records setup ownership and integrity metadata.
    # Keep stable protocol/ownership boundaries in new manifests; legacy fields
    # remain readable for compatibility but are not emitted by new writers.
    manifest_path = root / ".agents" / "manifest.json"
    manifest = {
        "protocol": "ACHP",
        "version": VERSION,
        "setup_skill": "agent-collaboration-setup",
        "managed_files": MANAGED_FILES,
        "project_owned_files": CREATE_IF_MISSING,
        "runtime_dependency_on_setup_skill": False,
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    write_text(root / ".agents" / "manifest.json", manifest_text, dry_run, actions)

    return actions


def validate(root: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    try:
        validate_existing_managed_blocks(root)
    except (OSError, ValueError) as exc:
        problems.append(f"managed block markers invalid: {exc}")

    agents = root / "AGENTS.md"
    if not agents.exists():
        problems.append("AGENTS.md missing")
    else:
        text = agents.read_text(encoding="utf-8")
        if AGENTS_BEGIN not in text or AGENTS_END not in text:
            problems.append("AGENTS.md ACHP managed block missing/incomplete")
        if "agent-collaboration-setup" not in text:
            problems.append("AGENTS.md setup/runtime boundary text missing")

    claude = root / "CLAUDE.md"
    if not claude.exists():
        problems.append("CLAUDE.md compatibility router missing")
    else:
        text = claude.read_text(encoding="utf-8")
        if CLAUDE_BEGIN not in text or CLAUDE_END not in text or "@AGENTS.md" not in text:
            problems.append("CLAUDE.md ACHP router missing/incomplete")

    gi = root / ".gitignore"
    if not gi.exists():
        problems.append(".gitignore missing")
    else:
        text = gi.read_text(encoding="utf-8")
        if GITIGNORE_BEGIN not in text or GITIGNORE_END not in text:
            problems.append(".gitignore ACHP runtime block missing")

    for rel in MANAGED_FILES + CREATE_IF_MISSING:
        if not (root / rel).exists():
            problems.append(f"missing {rel}")

    manifest = root / ".agents" / "manifest.json"
    if not manifest.exists():
        problems.append(".agents/manifest.json missing")
    else:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("protocol") != "ACHP":
                problems.append("manifest protocol is not ACHP")
            if data.get("runtime_dependency_on_setup_skill") is not False:
                problems.append("manifest runtime dependency boundary invalid")
        except Exception as exc:
            problems.append(f"manifest invalid JSON: {exc}")

    return not problems, problems


def uninstall(root: Path, dry_run: bool, purge_data: bool) -> list[str]:
    actions: list[str] = []
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

    manifest = root / ".agents" / "manifest.json"
    if manifest.exists():
        actions.append(f"remove {manifest}")
        if not dry_run:
            manifest.unlink()

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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-data", action="store_true")
    args = parser.parse_args()

    root = find_repo_root(args.root)
    print(f"Repository root: {root}")

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

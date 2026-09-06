#!/usr/bin/env python3
"""Expose this Skill checkout to Codex, OpenCode, and/or Claude Code."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

SKILL_NAME = "agent-collaboration-setup"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
        project = project.resolve()
        if {"codex", "opencode"} & hs:
            out.append(project / ".agents" / "skills" / SKILL_NAME)
        if "claude" in hs:
            out.append(project / ".claude" / "skills" / SKILL_NAME)

    # de-duplicate while preserving order
    seen = set()
    unique = []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            unique.append(p)
    return unique


def same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return False


def remove_destination(dest: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)


def install_one(source: Path, dest: Path, mode: str) -> str:
    if same_path(source, dest):
        return "already-source"

    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() and same_path(dest, source):
            return "linked"
        remove_destination(dest)

    if mode in {"auto", "symlink"}:
        try:
            dest.symlink_to(source, target_is_directory=True)
            return "linked"
        except OSError:
            if mode == "symlink":
                raise

    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )
    return "copied"


def check_one(source: Path, dest: Path) -> tuple[bool, str]:
    if not dest.exists() and not dest.is_symlink():
        return False, "missing"
    if not (dest / "SKILL.md").exists():
        return False, "SKILL.md missing"
    if dest.is_symlink():
        return same_path(dest, source), f"symlink -> {dest.resolve()}"
    # Copy mode: compare version as a lightweight freshness signal.
    src_v = (source / "VERSION").read_text(encoding="utf-8").strip()
    dst_v_path = dest / "VERSION"
    dst_v = dst_v_path.read_text(encoding="utf-8").strip() if dst_v_path.exists() else "unknown"
    ok = src_v == dst_v
    return ok, f"copy version={dst_v}, source={src_v}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--harness",
        nargs="+",
        default=["all"],
        choices=["all", "codex", "opencode", "claude"],
    )
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--mode", choices=["auto", "symlink", "copy"], default="auto")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    source = repo_root()
    dests = destinations(args.harness, args.scope, args.project)

    if args.check:
        failed = False
        for dest in dests:
            ok, detail = check_one(source, dest)
            print(f"[{'OK' if ok else 'FAIL'}] {dest}: {detail}")
            failed |= not ok
        return 1 if failed else 0

    if args.uninstall:
        for dest in dests:
            if same_path(source, dest):
                print(f"[SKIP] {dest}: this is the source checkout")
                continue
            if dest.exists() or dest.is_symlink():
                remove_destination(dest)
                print(f"[REMOVED] {dest}")
            else:
                print(f"[ABSENT] {dest}")
        return 0

    for dest in dests:
        result = install_one(source, dest, args.mode)
        print(f"[{result.upper()}] {dest}")

    print("Installation complete. Restart/reload the harness only if it does not detect the Skill immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

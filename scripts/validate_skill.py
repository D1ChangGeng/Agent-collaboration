#!/usr/bin/env python3
"""Minimal portable validation for this Agent Skill repository."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
EXPECTED_SKILL_NAME = "agent-collaboration-setup"

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "VERSION",
    "scripts/install_skill.py",
    "scripts/project_setup.py",
    "assets/scaffold/AGENTS_BLOCK.md",
    "assets/scaffold/CLAUDE_BLOCK.md",
    "assets/scaffold/.agents/protocol/CAPABILITIES.md",
    "assets/scaffold/.agents/protocol/RELAY.md",
    "assets/scaffold/.agents/protocol/GIT-SYNC.md",
    "assets/scaffold/.agents/protocol/KNOWLEDGE.md",
]


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    _, fm, _body = text.split("---", 2)
    data: dict[str, str] = {}
    for raw in fm.strip().splitlines():
        if not raw.strip() or raw.startswith(" ") or ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def main() -> int:
    problems = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            problems.append(f"missing {rel}")

    if SKILL.exists():
        text = SKILL.read_text(encoding="utf-8")
        try:
            fm = parse_frontmatter(text)
            name = fm.get("name", "")
            desc = fm.get("description", "")
            # The canonical Skill slug is intentionally independent from the
            # source repository directory name.  This repository is
            # `Agent-collaboration`, while the installable Skill remains
            # `agent-collaboration-setup`.
            if name != EXPECTED_SKILL_NAME:
                problems.append(
                    f"skill name '{name}' does not match canonical Skill slug "
                    f"'{EXPECTED_SKILL_NAME}'"
                )
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                problems.append("skill name is not portable lowercase kebab-case")
            if not (1 <= len(name) <= 64):
                problems.append("skill name length must be 1..64")
            if not (1 <= len(desc) <= 1024):
                problems.append("description length must be 1..1024")
            if "setup-only" not in desc.lower() and "setup" not in desc.lower():
                problems.append("description should make setup-only scope explicit")
            forbidden = {
                "disable-model-invocation",
                "context",
                "agent",
                "background",
                "hooks",
                "paths",
                "shell",
            }
            present = forbidden.intersection(fm)
            if present:
                problems.append(f"non-portable harness-specific frontmatter present: {sorted(present)}")
        except Exception as exc:
            problems.append(str(exc))

    agents_block = ROOT / "assets/scaffold/AGENTS_BLOCK.md"
    if agents_block.exists():
        text = agents_block.read_text(encoding="utf-8")
        for needle in [
            "Manual user forwarding",
            "Never infer capability from a Harness/product name",
            "Session messaging and repository synchronization are independent",
            ".agents/knowledge/",
        ]:
            if needle not in text:
                problems.append(f"AGENTS block missing invariant: {needle}")

    claude = ROOT / "assets/scaffold/CLAUDE_BLOCK.md"
    if claude.exists() and "@AGENTS.md" not in claude.read_text(encoding="utf-8"):
        problems.append("Claude compatibility block must import @AGENTS.md")

    if problems:
        print("Validation failed:")
        for p in problems:
            print(f"- {p}")
        return 1

    print("Skill repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

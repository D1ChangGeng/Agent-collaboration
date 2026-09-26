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
    "scripts/workspace_setup.py",
    "assets/scaffold/AGENTS_BLOCK.md",
    "assets/scaffold/CLAUDE_BLOCK.md",
    "assets/scaffold/.agents/protocol/CAPABILITIES.md",
    "assets/scaffold/.agents/protocol/RELAY.md",
    "assets/scaffold/.agents/protocol/GIT-SYNC.md",
    "assets/scaffold/.agents/protocol/KNOWLEDGE.md",
    "assets/scaffold/workspace/AGENTS_BLOCK.md",
    "assets/scaffold/workspace/GITIGNORE_BLOCK.txt",
    "assets/scaffold/workspace/ROUTE_AGENTS.md",
    "assets/scaffold/workspace/.agents/README.md",
    "assets/scaffold/workspace/.agents/config.yaml",
    "assets/scaffold/workspace/.agents/settings.yaml",
    "assets/scaffold/workspace/.agents/protocol/CAPABILITIES.md",
    "assets/scaffold/workspace/.agents/protocol/RELAY.md",
    "assets/scaffold/workspace/.agents/protocol/GIT-SYNC.md",
    "assets/scaffold/workspace/.agents/protocol/KNOWLEDGE.md",
    "assets/scaffold/workspace/.agents/protocol/SOURCE-STATE.md",
    "assets/scaffold/workspace/.agents/coordination/ROOT.md",
    "assets/scaffold/workspace/.agents/coordination/ROOT-BASELINE.md",
    "assets/scaffold/workspace/.agents/coordination/PROJECT.md",
    "assets/scaffold/workspace/.agents/state/source-state.yaml",
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
            version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
            metadata_version = fm.get("version", "")
            if metadata_version and metadata_version != version_file:
                problems.append(f"SKILL metadata version '{metadata_version}' does not match VERSION '{version_file}'")
        except Exception as exc:
            problems.append(str(exc))

    # Both new scaffold modes carry the same ACHP release identity.  Check
    # them against VERSION so a freshly installed project cannot inherit a
    # stale protocol release marker.
    try:
        version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        for rel in (
            "assets/scaffold/.agents/config.yaml",
            "assets/scaffold/workspace/.agents/config.yaml",
        ):
            config_text = (ROOT / rel).read_text(encoding="utf-8")
            match = re.search(r'(?m)^\s*version:\s*["\']([^"\']+)["\']\s*$', config_text)
            if not match:
                problems.append(f"{rel} is missing protocol version")
            elif match.group(1) != version_file:
                problems.append(
                    f"{rel} protocol version '{match.group(1)}' does not match VERSION '{version_file}'"
                )
    except Exception as exc:
        problems.append(f"scaffold version check failed: {exc}")

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

    workspace_agents = ROOT / "assets/scaffold/workspace/AGENTS_BLOCK.md"
    if workspace_agents.exists():
        text = workspace_agents.read_text(encoding="utf-8")
        for needle in [
            "Project Collaboration Root",
            "not\nassumed to be a Git repository or an execution checkout",
            "Do not assume this file is automatically inherited",
            "SOURCE-STATE.md",
        ]:
            if needle not in text:
                problems.append(f"workspace AGENTS block missing invariant: {needle}")

    source_state = ROOT / "assets/scaffold/workspace/.agents/protocol/SOURCE-STATE.md"
    if source_state.exists() and "unknown" not in source_state.read_text(encoding="utf-8"):
        problems.append("workspace source-state contract must define explicit unknown values")

    # The Route source-state asset is an opt-in example, not a default runtime
    # record. Keep the packaged template from regressing into a fabricated
    # baseline or a second Harness/session status surface.
    route_source_template = ROOT / "assets/scaffold/workspace/.agents/state/source-state.yaml"
    if route_source_template.exists():
        text = route_source_template.read_text(encoding="utf-8")
        if "Do not copy this file unchanged" not in text:
            problems.append("Route source-state template must be explicitly opt-in")
        for forbidden in (
            "execution_endpoint:",
            "harness:",
            "session:",
            "freshness:",
            "refresh_trigger:",
        ):
            if re.search(rf"(?m)^\s*(?!#).*{re.escape(forbidden)}", text):
                problems.append(
                    f"Route source-state template must not persist runtime field: {forbidden[:-1]}"
                )

    if problems:
        print("Validation failed:")
        for p in problems:
            print(f"- {p}")
        return 1

    print("Skill repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

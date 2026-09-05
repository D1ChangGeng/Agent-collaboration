# Project Coordination Profile

This file is project-owned after first creation. ACHP upgrades preserve it.

## Identity

- Project: Agent-collaboration
- Repository: Agent-collaboration (local repository; GitHub publication pending)
- Skill slug: agent-collaboration-setup
- Primary branch: main (to be initialized)
- Project type: existing source recovered from the v0.1.0 Skill archive
- Current phase: v0.1.0 recovery, self-hosting, and first public-release preparation

## Collaboration topology

- Sessions involved: current Codex session; future sessions are not yet enumerated
- Hosts involved: current local host; future hosts unknown
- Expected topology: unknown unless a task explicitly establishes otherwise
- User available for manual relay: yes

## Roles

- Coordinator: assigned per task/session
- Executor: assigned per task/session
- Reviewer: assigned per task/session
- Combined roles, if any: a single session may combine roles when explicitly appropriate

## Product / outcome

Agent-collaboration develops a Harness-agnostic Agent Collaboration & Handoff
Protocol (ACHP) and the `agent-collaboration-setup` setup-only Skill. The Skill
installs or maintains the repository-native runtime scaffold, then exits the
normal collaboration runtime. Product and design authority is split between
`SKILL.md`, `README.md` / `README.zh-CN.md`, and `references/`.

## Current milestone

Current milestone: establish the recovered v0.1.0 source as the
`Agent-collaboration` repository, dogfood ACHP in this repository, initialize
the project knowledge plane, validate the release, and publish when GitHub
access is available.

## Critical project-specific constraints

- Keep the repository name `Agent-collaboration` separate from the installable
  Skill slug `agent-collaboration-setup`.
- Keep the Skill setup-only; normal collaboration runs from `AGENTS.md` and
  `.agents/` and must not depend on the Skill being installed.
- Treat manual user relay as a first-class transport and automatic relay as a
  capability-verified enhancement only.
- Keep message relay state independent from Git repository synchronization.
- Keep `.agents/runtime/` machine/session-local and ignored; `.agents/knowledge/`
  is the durable project Knowledge Plane.
- Preserve project-owned profile, tasks, handoffs, and knowledge during setup
  upgrades and default uninstall.

## Authoritative routes

| Need | Location |
|---|---|
| Product intent | `SKILL.md`, `README.md`, `README.zh-CN.md` |
| Architecture | `references/DESIGN.md`, `references/HARNESS-COMPATIBILITY.md`, `.agents/protocol/` |
| Roadmap | `.agents/knowledge/observations/`, future accepted Decisions, and release notes |
| Current implementation status | `scripts/`, `tests/`, `.github/workflows/validate.yml`, `CHANGELOG.md` |
| Decisions | `.agents/knowledge/decisions/` |
| Durable project knowledge | `.agents/knowledge/` |
| Active tasks | `.agents/coordination/tasks/` |
| Handoffs | `.agents/coordination/handoffs/` |

## Version and release identity

- Current version: v0.1.0 (`VERSION`)
- Release identity: setup-only `agent-collaboration-setup` Skill, published from
  the `Agent-collaboration` source repository
- Public GitHub owner, URL, remote, and Release state: pending live verification

## Validation routes

```text
python scripts/validate_skill.py
python -m unittest discover -s tests -v
python scripts/project_setup.py validate --root .
node <installed-self-evolution>/references/bin/kb.mjs check --project-root . --format text
git diff --check
```

## Current primary goal

Complete the first verified local repository and, when credentials and network
access permit, create/push the public `Agent-collaboration` repository and attach
the correctly scoped v0.1.0 release artifacts. Do not expand into v0.2 runtime
services or new Harness adapters during this initialization.

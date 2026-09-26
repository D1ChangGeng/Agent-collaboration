# Project Coordination Profile

This file is project-owned after first creation. ACHP upgrades preserve it.

## Identity

- Project: Agent-collaboration
- Repository: Agent-collaboration (local Git repository; public GitHub repository published as `D1ChangGeng/Agent-collaboration`)
- Skill slug: agent-collaboration-setup
- Primary branch: `main`
- Project type: existing source recovered from the v0.1.0 Skill archive
- Setup release: v0.4.0 on Workspace schema 0.3.
- Active Runtime phase: user-authorized P1/P2 implementation under
  `docs/runtime/UPGRADE-CONTRACT.md`; support remains Gate-scoped.

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

Setup milestone: maintain the verified setup-only baseline and the nested
Project Collaboration Workspace / Route layout in the product Git repository,
with standalone compatibility and the setup/runtime boundary preserved.
The v0.3.0 Workspace/Route persistence model remains
the published schema baseline; v0.4.0 hardens lifecycle safety and Agent-facing
operation guidance without adding runtime recovery state.

## Critical project-specific constraints

- Keep the repository name `Agent-collaboration` separate from the installable
  Skill slug `agent-collaboration-setup`.
- Keep the Skill setup-only; normal collaboration runs from `AGENTS.md` and
  `.agents/` and must not depend on the Skill being installed.
- The setup profile treats manual user relay as a first-class transport.
  The adopted Runtime profile uses system-managed delivery and incident-based
  Human Bridge under `docs/runtime/UPGRADE-CONTRACT.md`.
- Keep message relay state independent from Git repository synchronization.
- Keep Harness/session capability observations in the current execution context;
  `.agents/knowledge/` is the durable project Knowledge Plane.
- Preserve project-owned profile, tasks, handoffs, and knowledge during setup
  upgrades and default uninstall.
- Keep management, source-state, and execution responsibilities logically
  distinct within the shared project Git repository. Local and remote clones
  retain the same nested management layout; missing source-state facts remain
  `unknown` or `unverified`.
- Treat the Root registry as stable control-plane metadata, not a per-turn
  shared status log; Route knowledge and dynamic state remain Route-owned.
- The existing repository-mode `.agents/config.yaml` is project-owned legacy
  configuration and may retain its original `protocol.version: "0.1.0"` during
  Skill upgrades; it is not the Skill release identity. Fresh repository
  scaffolds use the current release version, and Workspace scaffolds use the
  current Workspace protocol release.

## Authoritative routes

| Need | Location |
|---|---|
| Product intent | `SKILL.md`, `README.md`, `README.zh-CN.md` |
| Runtime adoption and acceptance | `docs/runtime/UPGRADE-CONTRACT.md`, `docs/runtime/gate-contract.json` |
| Architecture | `references/DESIGN.md`, `references/HARNESS-COMPATIBILITY.md`, `.agents/protocol/`, `assets/scaffold/workspace/` |
| Roadmap | `.agents/knowledge/observations/`, future accepted Decisions, and release notes |
| Current implementation status | `scripts/`, `tests/`, `.github/workflows/validate.yml`, `CHANGELOG.md` |
| Decisions | `.agents/knowledge/decisions/` |
| Durable project knowledge | `.agents/knowledge/` |
| Active tasks | `.agents/coordination/tasks/` |
| Handoffs | `.agents/coordination/handoffs/` |

## Version and release identity

- Current version: v0.4.0 (`VERSION`)
- Release identity: setup-only `agent-collaboration-setup` Skill, published from
  the `Agent-collaboration` source repository
- Public GitHub owner: `D1ChangGeng`
- Repository: `https://github.com/D1ChangGeng/Agent-collaboration`
- Published releases: `v0.1.0`, `v0.2.0`, `v0.3.0`, `v0.4.0`

## Validation routes

```text
python scripts/validate_skill.py
python -m unittest discover -s tests -v
python scripts/project_setup.py validate --root .
python scripts/project_setup.py workspace validate --root <workspace>
python scripts/project_setup.py route list --workspace <workspace>
node <installed-self-evolution>/references/bin/kb.mjs check --project-root . --format text
git diff --check
```

## Current primary goal

Implement and verify the authorized Collaboration Runtime through P1 Local
Durable Slice and ordered P2 Codex-to-Codex / Codex-to-OpenCode Gates. Preserve
the released Workspace schema 0.3 and setup safety while adding independently
adopted Runtime mechanisms. Current Gate status belongs to the Runtime Route's
coordination records and actual evidence, not the setup version.

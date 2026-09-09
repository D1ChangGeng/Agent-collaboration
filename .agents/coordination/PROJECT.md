# Project Coordination Profile

This file is project-owned after first creation. ACHP upgrades preserve it.

## Identity

- Project: Agent-collaboration
- Repository: Agent-collaboration (local Git repository; public GitHub repository published as `D1ChangGeng/Agent-collaboration`)
- Skill slug: agent-collaboration-setup
- Primary branch: `main`
- Project type: existing source recovered from the v0.1.0 Skill archive
- Current phase: v0.4.0 released user-journey safety baseline on the minimal
  Workspace schema 0.3 model

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

Current milestone: maintain the verified setup-only baseline and the explicit
non-Git Project Collaboration Workspace / Route control plane while preserving
the setup/runtime boundary. The v0.3.0 Workspace/Route persistence model remains
the published schema baseline; v0.4.0 hardens lifecycle safety and Agent-facing
operation guidance without adding runtime recovery state.

## Critical project-specific constraints

- Keep the repository name `Agent-collaboration` separate from the installable
  Skill slug `agent-collaboration-setup`.
- Keep the Skill setup-only; normal collaboration runs from `AGENTS.md` and
  `.agents/` and must not depend on the Skill being installed.
- Treat manual user relay as a first-class transport and automatic relay as a
  capability-verified enhancement only.
- Keep message relay state independent from Git repository synchronization.
- Keep Harness/session capability observations in the current execution context;
  `.agents/knowledge/` is the durable project Knowledge Plane.
- Preserve project-owned profile, tasks, handoffs, and knowledge during setup
  upgrades and default uninstall.
- Keep management Workspaces distinct from source repositories and execution
  endpoints; missing source-state facts remain `unknown` or `unverified`.
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

Maintain the released Workspace schema 0.3 persistence model, keep validation
and upgrade behavior fail-closed, and preserve the independent task boundary
for Root, A Route, and B Route work. Product or Route changes require their own
task and evidence; they are not implied by the Skill release.

# Project Coordination Profile

This file is project-owned after first creation. ACHP upgrades preserve it.

## Identity

- Project: Agent-collaboration
- Repository: Agent-collaboration (local Git repository; public GitHub repository published as `D1ChangGeng/Agent-collaboration`)
- Skill slug: agent-collaboration-setup
- Primary branch: `main`
- Project type: existing source recovered from the v0.1.0 Skill archive
- Current phase: v0.2.0 Workspace/Route architecture upgrade and local validation

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

Current milestone: extend the verified v0.1.0 setup-only baseline with an
explicit non-Git Project Collaboration Workspace / Route control plane, while
keeping the repository-oriented mode compatible and preserving the setup/runtime
boundary. The v0.2.0 changes in this working tree are local and not published.

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
- Keep management Workspaces distinct from source repositories and execution
  endpoints; missing source-state facts remain `unknown` or `unverified`.
- Treat the Root registry as stable control-plane metadata, not a per-turn
  shared status log; Route knowledge and dynamic state remain Route-owned.

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

- Current version: v0.2.0 (`VERSION`)
- Release identity: setup-only `agent-collaboration-setup` Skill, published from
  the `Agent-collaboration` source repository
- Public GitHub owner: `D1ChangGeng`
- Repository: `https://github.com/D1ChangGeng/Agent-collaboration`
- Published release: `v0.1.0`; v0.2.0 is local and has not been pushed or released

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

Complete and review the v0.2.0 Workspace/Route setup baseline, validate the
dogfood Root at `D:\Chatgpt\Agent`, and keep A/B Route semantic migration as an
independent later phase. Do not expand into runtime services, a broker/daemon,
UI, or new Harness adapters without an explicitly accepted design and
validation plan.

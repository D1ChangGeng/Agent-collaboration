---
kind: decision
id: adr-001-setup-runtime-boundary
status: accepted
date: 2026-09-05
scope:
  - "SKILL.md"
  - "scripts/project_setup.py"
  - "assets/scaffold/**"
  - "AGENTS.md"
  - ".agents/**"
supersedes: null
---

# Context

The repository contains an installable Skill and the runtime protocol that the
Skill installs. Coupling normal work to the Skill would make every target
project depend on an installer being present and would blur setup ownership with
runtime coordination.

# Decision

`agent-collaboration-setup` is setup-only. It may bootstrap, adopt, upgrade,
repair, validate, or uninstall the scaffold. After setup, normal collaboration
is governed by `AGENTS.md` and `.agents/`; the manifest must report
`runtime_dependency_on_setup_skill: false`.

# Alternatives considered

- Keep the Skill loaded for every task: rejected because it creates a hidden
  runtime dependency and duplicates protocol authority.
- Copy all protocol text into every Harness adapter: rejected because it creates
  multiple truths and drift.

# Consequences

Projects can continue normal Coordinator/Executor/Reviewer work after removing
the Skill. Setup changes remain explicit and reviewable. Runtime behavior must be
verified from repository-native files, tests, and Git history.

# Reconsider when

Reconsider only if a future adopted protocol version explicitly changes the
installation/runtime contract and supplies a migration path.

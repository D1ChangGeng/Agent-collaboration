# `.agents/`

Harness-neutral project collaboration state.

The root `AGENTS.md` is the runtime entry point. This directory contains deeper protocol routes, coordination artifacts, and durable knowledge.

## Boundaries

- `protocol/` — stable ACHP semantics.
- `coordination/` — project profile, roles, tasks, handoffs, templates.
- `knowledge/` — durable shared project knowledge.
- Harness/session context — machine/session-local capability observations; not a
  required project directory.

The `agent-collaboration-setup` Skill is not a runtime dependency.

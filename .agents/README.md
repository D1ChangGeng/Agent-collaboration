# `.agents/`

Harness-neutral project collaboration state.

The root `AGENTS.md` is the runtime entry point. This directory contains deeper protocol routes, coordination artifacts, and durable knowledge.

## Boundaries

- `protocol/` — stable ACHP semantics.
- `coordination/` — project profile, roles, tasks, handoffs, templates.
- `knowledge/` — durable shared project knowledge.
- `runtime/` — machine/session-local capability observations; Git-ignored.

The `agent-collaboration-setup` Skill is not a runtime dependency.

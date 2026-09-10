<!-- ACHP-WORKSPACE:BEGIN -->
## ACHP Project Collaboration Root

This directory is a Project Collaboration Root: a durable management workspace
for project identity, routes, coordination, and source-state evidence. It is not
assumed to be a Git repository or an execution checkout.

### Startup

1. Read `.agents/coordination/PROJECT.md` and
   `.agents/coordination/ROOT-BASELINE.md`.
2. Read `.agents/coordination/routes.yaml` to discover Route Nodes.
3. Read only the matching route's own `AGENTS.md` and `.agents/knowledge/` when
   working on that route. Root knowledge is not a replacement for route-owned
   knowledge.
4. Read `.agents/protocol/SOURCE-STATE.md` before making claims about code,
   branches, endpoints, or execution status.
5. For a management-workspace task, do not invent branch, commit, or working
   tree facts. Use `unknown`, `unverified`, or `not-measured` until evidence is
   bound to a specific Source State.

### Scope and ownership

- Root owns stable project identity, route registry, cross-route coordination,
  and the Root↔Route migration contract.
- A Route Node owns its identity metadata, durable goals, decisions, knowledge,
  and verified source evidence. The Root registry owns lifecycle status and
  display name; live Session progress remains in the current Harness context.
- An Execution Endpoint is replaceable runtime capacity, not a permanent Route
  identity.
- A Source Repository and its Repository State are separate from this
  management workspace.
- Do not assume this file is automatically inherited by a child Route. Harness
  discovery is runtime-specific; use the explicit Root contract path.
- `self-evolution` owns durable-knowledge lifecycle; ACHP owns collaboration
  topology and state boundaries.
- Harness/session context and capability observations are local to the running
  environment. They are not required Project Collaboration Workspace state.

### AGENTS.md admission and natural evolution

This Root file contains only always-on collaboration invariants: stable identity
and role boundaries, Root/Route/Endpoint/Source-State separation, high-level
topology and behavior rules, cross-session continuity, and recurring high-cost
corrections that every related session must know before work begins.

Promote a new rule here only when real work shows that it is stable across
future sessions or Routes, startup-critical, and not reliably supplied by
retrieved Root or Route knowledge. Current project state, implementation
details, design rationale, task progress, engineer reports, and temporary
evidence remain in their authoritative Route, state, knowledge, or source
records.

`self-evolution` owns knowledge discovery, capture, retrieval, correction,
verification, and maintenance. The Root file does not duplicate that lifecycle
and must not become a work log or a second source of truth.

See `.agents/coordination/ROOT-BASELINE.md`, `.agents/protocol/RELAY.md`,
`.agents/protocol/GIT-SYNC.md`, and `.agents/protocol/SOURCE-STATE.md` for the
deeper contracts.
<!-- ACHP-WORKSPACE:END -->

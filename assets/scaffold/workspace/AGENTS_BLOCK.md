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
- A Route Node owns its goals, route-specific identity, state, knowledge, and
  engineer-facing continuity.
- An Execution Endpoint is replaceable runtime capacity, not a permanent Route
  identity.
- A Source Repository and its Repository State are separate from this
  management workspace.
- Do not assume this file is automatically inherited by a child Route. Harness
  discovery is runtime-specific; use the explicit Root contract path.
- `self-evolution` owns durable-knowledge lifecycle; ACHP owns collaboration
  topology and state boundaries.
- `.agents/runtime/` is machine/session-local and must not become project truth.

See `.agents/coordination/ROOT-BASELINE.md`, `.agents/protocol/RELAY.md`,
`.agents/protocol/GIT-SYNC.md`, and `.agents/protocol/SOURCE-STATE.md` for the
deeper contracts.
<!-- ACHP-WORKSPACE:END -->

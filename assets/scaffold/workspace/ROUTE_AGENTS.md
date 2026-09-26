<!-- ACHP-ROUTE:BEGIN -->
## ACHP Route Node

Route ID: `{{ROUTE_ID}}`

Display name and lifecycle status are authoritative in the Root registry. This
file carries only stable Route identity, ownership, and startup boundaries.

This directory is a Route Node under a Project Collaboration Root. Its stable
identity, long-lived goals, Route-owned knowledge, decisions, and source evidence
remain here. The Root contract is authoritative for shared project collaboration
semantics:

```text
{{ROOT_CONTRACT}}
```

When this path is not the direct session working directory, Harness instruction
discovery may not load the parent Root `AGENTS.md`. Read the explicit Root
contract above when the task crosses Root/Route boundaries; do not copy the Root
contract into this file.

Source Repository, branch, commit, tree, worktree, push, and receiver-sync claims
remain unknown until independently evidenced. Create
`.agents/state/source-state.yaml` only when verified source facts need a durable
Route-owned record. Harness, Session, and live Endpoint observations stay in the
current execution context unless a specific long-term fact passes the normal
durable-knowledge test.

## Always-on content boundary

Keep this file focused on stable Route identity, ownership, topology, and other
startup-critical invariants that must survive a new Route session. Promote a
new Route rule only when real work shows that it is stable across future Route
sessions and cannot be reliably supplied by retrieved knowledge. Current Session
progress and temporary evidence remain in Harness context; durable decisions and
source facts stay in their existing knowledge or source authorities.

`self-evolution` owns knowledge discovery, capture, retrieval, correction,
verification, and maintenance; this file does not reproduce that lifecycle or
become a Route work log.
<!-- ACHP-ROUTE:END -->

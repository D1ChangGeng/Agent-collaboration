<!-- ACHP-ROUTE:BEGIN -->
## ACHP Route Node: {{ROUTE_NAME}}

Route ID: `{{ROUTE_ID}}`

This directory is a Route Node under a Project Collaboration Root. Its stable
route identity, route-owned state, and route knowledge remain here. The Root
contract is authoritative for shared project collaboration semantics:

```text
{{ROOT_CONTRACT}}
```

When this path is not the direct session working directory, Harness instruction
discovery may not load the parent Root `AGENTS.md`. Read the explicit Root
contract above when the task crosses Root/Route boundaries; do not copy the Root
contract into this file.

Source Repository, Execution Endpoint, branch, commit, tree, and push state are
unknown until recorded in `.agents/state/source-state.yaml` with evidence.

## Always-on content boundary

Keep this file focused on stable Route identity, ownership, topology, and other
startup-critical invariants that must survive a new Route session. Promote a
new Route rule only when real work shows that it is stable across future Route
sessions and cannot be reliably supplied by retrieved knowledge. Current state,
implementation details, decisions, reports, and temporary evidence belong in
the Route's `.agents/knowledge/`, state, or authoritative source records.

`self-evolution` owns knowledge discovery, capture, retrieval, correction,
verification, and maintenance; this file does not reproduce that lifecycle or
become a Route work log.
<!-- ACHP-ROUTE:END -->

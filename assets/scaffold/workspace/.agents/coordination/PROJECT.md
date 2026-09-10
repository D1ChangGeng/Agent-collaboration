# Project Collaboration Root Profile

## Identity

- Project:
- Root ID: see `.agents/manifest.json`; its `root_id` is authoritative
- Root kind: Project Collaboration Workspace
- Primary layout: Nested Management Root within the Source Checkout Root
- Management path:
- Repository-relative management path:
- Source repository: unknown until bound by Source State Evidence
- Execution endpoints: unknown until bound by endpoint evidence
- Primary branch: unknown until verified in the relevant source checkout

## Repository layout

Product code, management documents, knowledge, and Route directories are tracked
in the same Git repository. Local and remote hosts use distinct clones with the
same repository-relative Management Root and Route layout; absolute paths may
differ. Synchronization uses explicit Git operations.

In this nested layout, the Source Checkout Root's `.gitignore` owns scoped rules
for transient files and secrets; the Management Root has no child `.gitignore`.
Standalone management workspaces remain a compatibility deployment.

## Authoritative routes

| Need | Location |
|---|---|
| Root contract | `.agents/coordination/ROOT-BASELINE.md` |
| Route registry | `.agents/coordination/routes.yaml` |
| Source-state schema | `.agents/protocol/SOURCE-STATE.md` |
| Root protocol | `.agents/protocol/` |
| Root knowledge | `.agents/knowledge/` |
| Root↔Route handoffs | `.agents/coordination/handoffs/` |

## Ownership

Root owns stable project identity, the Route registry, lifecycle status, display
names, and cross-route coordination. Routes own route identity metadata, durable
goals, decisions, knowledge, and verified source evidence. Execution Endpoints
are replaceable; live Session progress remains in Harness context.
Self-evolution owns knowledge lifecycle; it is not reimplemented by this
protocol.

## Evidence boundary

Management ownership, source state, and execution endpoints remain logically
separate when files share one Git repository. Missing source, endpoint, branch,
commit, tree, push, and receiver-sync fields are explicitly `unknown` or
`unverified`.

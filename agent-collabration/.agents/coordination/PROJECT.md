# Project Collaboration Root Profile

## Identity

- Project: Agent-collaboration
- Root ID: see `.agents/manifest.json`; its `root_id` is authoritative
- Root kind: Project Collaboration Workspace
- Management path: `agent-collabration/`, relative to the project source checkout
- Source repository: the containing `Agent-collaboration` Git repository
- Execution endpoints: unknown until bound by endpoint evidence
- Primary branch: use current evidence from the containing source checkout

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

This Management Root, its knowledge, and its Route directories are tracked with
product code in the containing Git repository. Local and remote clones retain
the same relative layout and synchronize explicitly through Git. Ignore rules
for local temporary data and secrets belong to the source checkout's root
`.gitignore`. Missing endpoint, branch, commit, tree, push, and receiver-sync
facts remain `unknown` or `unverified` until checked in the relevant clone.

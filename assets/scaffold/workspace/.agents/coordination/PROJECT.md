# Project Collaboration Root Profile

## Identity

- Project:
- Root ID: see `.agents/manifest.json`; its `root_id` is authoritative
- Root kind: Project Collaboration Workspace
- Management path:
- Source repository: unknown until bound by Source State Evidence
- Execution endpoints: unknown until bound by endpoint evidence
- Primary branch: not applicable at Root level

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

The Root is allowed to remain non-Git. Missing source, endpoint, branch, commit,
tree, push, and receiver-sync fields are explicitly `unknown` or `unverified`.

# ACS knowledge Skill catalog

Status: adopted P2 knowledge contract for MCP surface
acs-p2-mcp-workflow/6. The machine-readable catalog is
[p2-skill-contract.json](../p2-skill-contract.json).

ACS uses four instruction layers:

1. MCP server instructions expose the minimal startup and Project-context rule.
2. Skill metadata routes a material question to one knowledge domain.
3. SKILL.md provides its core model, invariants and reference map.
4. References provide entities, decision maps and tool implications on demand.

MCP tools provide authenticated data and controlled actions. Domain Commands
provide deterministic internal transitions. Skills provide reusable conceptual
knowledge that helps an Agent reason about current and future tasks. The setup
Skill remains procedural because installation and migration require guarded,
repeatable mechanics.

## Catalog

| Skill | Knowledge domain |
|---|---|
| agent-collaboration-setup | global installation, project adoption, Harness and web connection setup |
| acs-project-context | Project, Root, Route, Scope, project_id, context loading and multi-project topology |
| acs-collaboration-model | AgentSlot, Role, team, WorkItem, delegation, handoff and Message semantics |
| acs-runtime-model | Machine, Node, Runtime, Harness, Driver, Session, Attempt, Lease and Effect |
| acs-continuity-recovery | Inbox, Outbox, receipts, response, subscription, wake, retry and recovery |
| acs-source-evidence | SourceBinding, Git/filesystem state, Artifact, Evidence, digest and readback |
| acs-review-acceptance | Review types, independence, findings, finalization and AcceptedState |
| acs-policy-governance | Tenant, Grant, Policy, Profile, budget, OAuth, approval and data boundaries |
| acs-web-collaboration | remote MCP, ProjectContextPack, Tunnel, OAuth and web Source access |

## Knowledge admission

A knowledge Skill earns an independent module when its entities, authority,
state dimensions and decision rules remain useful across multiple unpredictable
tasks. A common action alone does not create a Skill. Direct tool selection
comes from tools/list. Project-specific facts come from ProjectContextPack,
AGENTS and project knowledge. Temporary task state remains in the Harness.

Each module has one concise SKILL.md and three lazy references:

- model.md for entities, relations, authority and storage;
- decisions.md for stable decision axes and boundary cases;
- tools.md for how public tools expose that domain.

## Retrieval behavior

The Harness initially sees only Skill name and description. It loads full
SKILL.md when the user's goal, current resource, tool result or unresolved state
matches that domain. It follows one reference at a time for a named question.

High-signal nouns in descriptions improve recall. Narrow domain boundaries,
explicit Related knowledge links and lazy references limit unnecessary context.
Tool results may include knowledge_hints containing Skill name, topic, reason
and reference. Hints advise retrieval and never grant authority.

See [RUNTIME-PRESENTATION.md](RUNTIME-PRESENTATION.md) for routing, load budgets,
ProjectContextPack integration and quality measures.

# ACS Skill workflow catalog

Status: adopted P2 Skill contract for MCP surface acs-p2-mcp-workflow/4.
The machine-readable catalog is [p2-skill-contract.json](../p2-skill-contract.json).

ACS uses three layers:

1. MCP tools provide authenticated data and controlled actions.
2. Skills provide reusable multi-tool workflows, branching, templates and completion criteria.
3. Starter prompts provide one-sentence user entry points.

Domain Command remains the internal deterministic state-transition protocol.
CLI commands remain setup and operator mechanisms. User workflows use Skills.
Harness slash aliases may select a Skill and share the same SKILL.md authority.

## Catalog

| Skill | User goal |
|---|---|
| agent-collaboration-setup | install ACS, adopt or maintain a project Management Root, configure local Harnesses and remote web connection |
| acs-project-manager | resume, understand, report and advance one project |
| acs-delegate-work | create or reuse work and delegate it with asynchronous response tracking |
| acs-handoff-work | transfer existing responsibility with source, evidence and acknowledgement continuity |
| acs-review-work | perform architecture, engineering, evidence or finalization review |
| acs-finalize-work | validate and commit accepted state at the authorized boundary |
| acs-recover-work | recover interrupted delivery, Session, Source or protected-effect state |
| acs-portfolio-manager | compare and coordinate multiple authorized projects |

The repository root SKILL.md is the active setup Skill. The Skill specifications
under this directory become installable runtime Skills after their required MCP
tools pass P2 conformance.

## Skill admission rule

Create a Skill when a recognizable user goal needs multiple tools, ordered
preconditions, context hydration, branching on incomplete results, a stable
output contract, or cross-Project, cross-AgentSlot or cross-Provider
coordination. A direct single-tool request uses the tool description.

## Shared invariants

Every project workflow carries project_id. Missing web context begins with
list_projects and load_project. Local context uses the same project_id from the
Management Root AGENTS block and manifest.

Source-dependent claims bind SourceBinding, revision, commit and tree. Message
delivery and source synchronization are independent. Skills preserve unresolved
items and evidence class. Mutations use idempotency, expected revision and
deadline.

See [STARTER-PROMPTS.md](STARTER-PROMPTS.md) for portable user entries.

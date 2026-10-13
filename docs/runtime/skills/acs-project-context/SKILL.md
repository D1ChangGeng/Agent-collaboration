---
name: acs-project-context
description: Project, Collaboration Root, Route, Scope, project_id, ProjectContextPack, multi-project, and Root Agent knowledge for ACS. Use when reasoning about project identity, context loading, Route boundaries, local versus web entry, or portfolio-wide state.
---

# acs-project-context

## Knowledge boundary

Project identity, management context and Root-to-Route topology. Work execution detail belongs to acs-collaboration-model; Runtime placement belongs to acs-runtime-model.

## Core invariants

- Root Agent is the project responsibility projection of an authenticated external Session with an explicit project_id and current Project context.
- Project, Root, Route and Scope are durable identities; Harness Session, machine and filesystem path are replaceable bindings.
- Every project-scoped tool carries project_id, and typed handles resolve to the same tenant and Project.
- Owner access follows trusted identity, active service and objects, explicit revocation, request deduplication and expected revisions; shared access also applies configured Grants and Policy.
- ProjectContextPack reports source and workspace revisions, completeness, evidence class and missing context.
- Current workspace context and fixed source snapshots preserve their distinct source identities.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Entity identity, hierarchy or storage | [model](references/model.md) |
| Choosing Project, Route, Scope or WorkItem boundaries | [decisions](references/decisions.md) |
| Project discovery and context tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: read_profile, list_projects, load_project, list_routes, list_work, list_activity, read_resource.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The owner product contract is `docs/runtime/OWNER-RUNTIME.md` in the verified
ACS release or source checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

---
name: acs-project-context
description: Project, Collaboration Root, Route, Scope, project_id, ProjectContextPack, multi-project, and Root Agent knowledge for ACS. Use when reasoning about project identity, context loading, Route boundaries, local versus web entry, or portfolio-wide state.
---

# acs-project-context

## Knowledge boundary

Project identity, management context and Root-to-Route topology. Work execution detail belongs to acs-collaboration-model; Runtime placement belongs to acs-runtime-model.

## Core invariants

- Root Agent is a role projection of an authenticated external Session, explicit project_id, current Project context and management Grant.
- Project, Root, Route and Scope are durable identities; Harness Session and filesystem path are replaceable bindings.
- Every project-scoped tool carries project_id, and typed handles must resolve to the same Project.
- Management context is revisioned and reports completeness, source revision, evidence class and missing context.

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

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

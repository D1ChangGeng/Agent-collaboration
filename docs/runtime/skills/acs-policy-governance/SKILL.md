---
name: acs-policy-governance
description: Tenant, Project isolation, authenticated subject, Grant, Policy, Role, Profile, budget, OAuth scope, approval, revocation, data boundary, secret reference, and audit knowledge for ACS. Use when deciding who may read, change, execute, review, or accept.
---

# acs-policy-governance

## Knowledge boundary

Authorization, governance and data policy. Domain entity semantics remain in their respective Skills.

## Core invariants

- Authenticated subject and tenant come from trusted transport or enrollment context.
- project_id selects an authorized Project and never grants access by itself.
- Grant, Policy, expected revision, deadline and protected-boundary checks authorize mutations.
- Revocation, expiry and budget are rechecked at dispatch, retry and protected effects.
- Secret values remain outside collaboration payloads and logs.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Governance entities and authority | [model](references/model.md) |
| Grant, Profile, approval and data decisions | [decisions](references/decisions.md) |
| Identity, Profile and governed action tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: read_profile, list_projects, list_connections, configure_team, accept_work, submit_command.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

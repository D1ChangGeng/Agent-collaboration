---
name: acs-policy-governance
description: Tenant, Project isolation, authenticated subject, Grant, Policy, Role, Profile, budget, OAuth scope, approval, revocation, data boundary, secret reference, and audit knowledge for ACS. Use when deciding who may read, change, execute, review, or accept.
---

# acs-policy-governance

## Knowledge boundary

Authorization, governance and data policy. Domain entity semantics remain in their respective Skills.

## Core invariants

- Authenticated subject, tenant and Authority context come from trusted transport or enrollment; project_id selects an active Project.
- A new single-owner installation records access_mode=owner; an existing configuration with unspecified access_mode retains shared behavior until explicit migration.
- Owner admission checks trusted credential, active service and objects, explicit revocation, request deduplication and expected revisions.
- Roles describe responsibilities; shared deployments separately apply per-subject Grants, Policy, Profile and budgets.
- Explicit business deadlines, real resource gateway claims, TLS, keys, Node identity, OAuth and replay checks apply at their actual boundaries.
- Secret values remain outside collaboration payloads and logs; historical recorded facts preserve their original provenance and integrity.

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

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The owner product contract is `docs/runtime/OWNER-RUNTIME.md` in the verified
ACS release or source checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

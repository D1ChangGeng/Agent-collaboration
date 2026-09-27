---
name: acs-runtime-model
description: Machine, Node, Runtime, Harness, Driver, Session, Endpoint, Attempt, Lease, Resource, capability, and Effect knowledge for ACS. Use when reasoning about execution placement, lifecycle, capabilities, fencing, or protected external effects.
---

# acs-runtime-model

## Knowledge boundary

Execution capacity and protected resources. Logical work ownership belongs to acs-collaboration-model; recovery sequencing belongs to acs-continuity-recovery.

## Core invariants

- Machine, Node, Runtime, Harness, Driver, Session and Endpoint are distinct identities.
- Capability is a scoped, directional, versioned observation with expiry and evidence.
- Attempt is one execution try; replacement creates a new Attempt and fences stale ownership.
- Lease binds owner, resource, generation, fencing token, Grant and expiry.
- Uncertain external effect requires authority readback before retry or compensation.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Runtime entity model and authority | [model](references/model.md) |
| Placement, replacement, lease and effect decisions | [decisions](references/decisions.md) |
| Runtime discovery and control tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_connections, list_harnesses, list_collaborators, stop_attempt, read_resource.

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
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)

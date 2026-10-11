---
name: acs-runtime-model
description: Machine, Node, Runtime, Harness, Driver, Session, Endpoint, Attempt, Lease, Resource, capability, and Effect knowledge for ACS. Use when reasoning about execution placement, lifecycle, capabilities, fencing, or protected external effects.
---

# acs-runtime-model

## Knowledge boundary

Execution capacity and protected resources. Logical work ownership belongs to acs-collaboration-model; recovery sequencing belongs to acs-continuity-recovery.

## Core invariants

- Machine, Node, Runtime, Harness, Driver, Session, Connection and Endpoint are distinct identities.
- Owner registrations persist through disconnection; execution reads actual process and Session state, reconnects and prepares the selected environment.
- Native modes use the selected user's tools, MCP servers, plugins, project/provider/model and approval configuration; interactive approval requires the actual native client handler.
- Attached Session read, send and cancellation follow the actual native API; process termination requires verified ownership of the stopped object.
- Attempt replacement preserves lineage; a Lease fences the concrete resource gateway that enforces it.
- Uncertain external effects require authority readback; explicit deadlines and shared capability windows retain their applicable clock checks.

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

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The owner product contract is `docs/runtime/OWNER-RUNTIME.md` in the verified
ACS release or source checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)

---
name: acs-collaboration-model
description: AgentSlot, Role, team, WorkItem, delegation, handoff, Message, response, dependency, and collaboration-state knowledge for ACS. Use when designing or reasoning about who works on what and how responsibilities and results move.
---

# acs-collaboration-model

## Knowledge boundary

Logical collaborators, work intent and communication. Harness lifecycle belongs to acs-runtime-model; delivery failure belongs to acs-continuity-recovery.

## Core invariants

- Root and Route describe responsibility extent; Engineer, Reviewer, Specialist and Finalizer describe duties.
- AgentSlot is a durable addressable responsibility inside a Scope; role metadata and candidate-specific reviewer independence are distinct.
- Owner configure_team stores slot, principal, role and Harness requirements as business configuration; shared mode applies its Grant, Policy and budget bindings.
- WorkItem intent, execution, Review, acceptance and effect state are independent dimensions.
- Delegation creates or selects work; handoff transfers existing responsibility and preserves lineage.
- Messages retain identity through retry and transport replacement; owner commands and messages use an optional explicit business deadline.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Entities, state dimensions and relationships | [model](references/model.md) |
| Team, delegation, handoff and dependency decisions | [decisions](references/decisions.md) |
| Collaboration management tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_collaborators, configure_team, create_work, revise_work, handoff_work, send_message, read_message.

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
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)

---
name: acs-collaboration-model
description: AgentSlot, Role, team, WorkItem, delegation, handoff, Message, response, dependency, and collaboration-state knowledge for ACS. Use when designing or reasoning about who works on what and how responsibilities and results move.
---

# acs-collaboration-model

## Knowledge boundary

Logical collaborators, work intent and communication. Harness lifecycle belongs to acs-runtime-model; delivery failure belongs to acs-continuity-recovery.

## Core invariants

- AgentSlot is a durable addressable responsibility inside a Scope; Role is descriptive and Grant is authoritative.
- configure_team changes bindings inside an existing Scope and preserves prior revisions.
- WorkItem intent, execution, review, acceptance and effect state are independent dimensions.
- Delegation creates or selects work; handoff transfers existing responsibility and preserves lineage.
- Message identity survives retries and transport changes.

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

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)

---
name: acs-continuity-recovery
description: Inbox, Outbox, delivery receipts, response tracking, subscriptions, waiting, wake, retry, deduplication, Session replacement, Human Bridge, and recovery knowledge for ACS. Use when collaboration is asynchronous, interrupted, duplicated, delayed, or uncertain.
---

# acs-continuity-recovery

## Knowledge boundary

Durable continuation and recovery. Work semantics belong to acs-collaboration-model; Runtime identities and fencing belong to acs-runtime-model.

## Core invariants

- Authority commit precedes accepted_by_authority; delivery and response receipts are separately observed.
- Owner Message and command validity is continuous by default; an explicit business deadline is optional.
- Async submission returns committed handles; sync waits for the target condition with an optional caller timeout.
- Durable Inbox and notification state survives disconnect and Session replacement; immediate delivery follows the actual Connection and Session.
- Busy Sessions queue until idle; readiness is read from the current native state before invocation.
- Retries preserve logical Message identity, initiating lineage and request deduplication; caller timeout preserves background tracking.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Delivery, response and subscription state | [model](references/model.md) |
| Timeout, replacement, ACK loss and Human Bridge decisions | [decisions](references/decisions.md) |
| Inbox, wait, notification and control tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: check_inbox, read_message, watch_changes, wait_for_response, set_notification, cancel_work, stop_attempt, list_activity.

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
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

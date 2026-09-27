---
name: acs-continuity-recovery
description: Inbox, Outbox, delivery receipts, response tracking, subscriptions, waiting, wake, retry, deduplication, Session replacement, Human Bridge, and recovery knowledge for ACS. Use when collaboration is asynchronous, interrupted, duplicated, delayed, or uncertain.
---

# acs-continuity-recovery

## Knowledge boundary

Durable continuation and recovery. Work semantics belong to acs-collaboration-model; Runtime identities and fencing belong to acs-runtime-model.

## Core invariants

- Authority commit precedes accepted_by_authority receipt.
- Delivery receipts are layered and missing layers remain unknown.
- Async response tracking and notification are created with Message submission.
- Busy Sessions use queue_until_idle; replacement preserves durable Inbox and subscription identity.
- Retries preserve logical Message identity and deduplicate native invocation.

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

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

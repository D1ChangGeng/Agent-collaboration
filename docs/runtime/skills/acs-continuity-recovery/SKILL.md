---
name: acs-continuity-recovery
description: Durable ACS Inbox/history, exact reply waiting and request identity across disconnects. Use when waiting, resuming communication or handling uncertain delivery.
---

# acs-continuity-recovery

## Knowledge boundary

Communication persistence and bounded technical recovery; model understanding and work outcomes are external.

## Core invariants

- Ordinary reads do not consume messages. A resource notification is a hint to read Inbox, not evidence of model consumption.
- Retain the original message handle and client_request_id. Waiting again does not send or invoke again; identical intentional sends remain distinct.
- Timeout and caller disconnect do not withdraw the message or a later explicit reply. any/all observe original relationships.
- An ACK can be unknown after an actual dispatch. Preserve that evidence; system notices do not satisfy waits for an Agent.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: check_inbox, list_messages, read_message, wait_for_response.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

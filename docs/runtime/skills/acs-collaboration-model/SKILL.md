---
name: acs-collaboration-model
description: Stable AgentSlot contacts, natural messages, explicit replies and scoped team configuration in ACS. Use when contacting, configuring or handing context to another Agent.
---

# acs-collaboration-model

## Knowledge boundary

Communication among autonomous Agents. Their planning, engineering review and work acceptance remain external.

## Core invariants

- Use send_message for questions, replies, corrections and natural handoffs. Provide natural content and a stable recipient.
- reply_to names original messages; only the actual recipient replying to the original sender satisfies their relationship.
- The default is invoke + async. message_only stores Inbox without Native activation; sync still waits for an explicit reply.
- No WorkItem, task handoff, Review or AcceptedState is created by normal communication.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_collaborators, configure_team, send_message, read_message, list_messages.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)

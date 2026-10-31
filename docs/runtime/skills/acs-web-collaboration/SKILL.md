---
name: acs-web-collaboration
description: ACS communication through authenticated remote MCP and real project context. Use for web-hosted Agent access, reconnecting and distinguishing server files from client-local files.
---

# acs-web-collaboration

## Knowledge boundary

Remote MCP entry, authentication and actual available receiving capabilities.

## Core invariants

- Use the actual authenticated subject/Slot binding and current tool schema. A read capability does not prove send or Native initiation support.
- After reconnecting, read durable Inbox/history and retain the original references. Notifications are not replies.
- OAuth consent, ingress, Native readiness and configuration adoption are separate; report missing capabilities honestly.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_projects, load_project, check_inbox, read_message.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

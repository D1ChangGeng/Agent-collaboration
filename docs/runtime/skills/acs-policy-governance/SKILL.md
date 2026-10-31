---
name: acs-policy-governance
description: Trusted Client and Slot caller bindings, project-scoped Grants and ACS management boundaries. Use when reasoning about who can contact, read or configure whom.
---

# acs-policy-governance

## Knowledge boundary

Authentication and authority. Message text and a supplied reference cannot grant permission.

## Core invariants

- A trusted Client can be unbound to a Native Session. A lower caller does not become a Client by omitting its Slot.
- Distinct Agents sharing a principal require trusted Slot bindings; from text or arbitrary Session IDs are not identity.
- Upper management inherits lower role eligibility within actual authorization. Role labels do not invent operational permissions.
- Private message reads require the actual participant identity; optional filters narrow visibility.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: read_profile, configure_team, list_collaborators.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

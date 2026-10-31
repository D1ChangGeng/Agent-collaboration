---
name: acs-review-acceptance
description: External engineering review and acceptance using ACS communication and source evidence. Use when coordinating an independent review or reporting findings; decisions remain with external Agents.
---

# acs-review-acceptance

## Knowledge boundary

Engineering judgment outside ACS. The bridge transmits messages and authorized source references without a Review lifecycle.

## Core invariants

- Describe the candidate, findings and evidence in natural content and external repository files.
- The reviewer independently checks actual source and reports through send_message. ACS does not decide whether work is acceptable.
- A clarification or progress message may satisfy a communication wait; that is not acceptance or business completion.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: send_message, read_message, read_source, read_diff.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-source-evidence](../acs-source-evidence/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)

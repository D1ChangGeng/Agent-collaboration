---
name: acs-runtime-model
description: Actual Node, endpoint and Native Session bindings for ACS. Use when selecting receiving capacity, checking readiness or distinguishing configuration from real Native contact.
---

# acs-runtime-model

## Knowledge boundary

Native receiving capacity and one authorized initiation, separate from message authorship and Agent reasoning.

## Core invariants

- list_harnesses is observation only: it does not prepare, spawn, resume or invoke.
- Configuration commit, receiver preparation and observed Native Session are distinct facts; only a real Adapter supplies a Session ID.
- Busy, offline and unknown are different. Use supported queueing; an uncertain dispatch is not permission to invoke again.
- Native final output is not a reply. ACS does not continuously observe execution or decide work completion.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_connections, list_harnesses, configure_team.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-continuity-recovery](../acs-continuity-recovery/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)

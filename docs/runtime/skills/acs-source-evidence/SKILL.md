---
name: acs-source-evidence
description: Actual machine files, repository readers and source provenance for ACS communication. Use when sharing paths, choosing an authorized reader or verifying the bytes actually inspected.
---

# acs-source-evidence

## Knowledge boundary

Source provenance and actual file access. ACS messages carry references, not repository synchronization.

## Core invariants

- Prefer accessible paths, Git and existing authorized readers. Record the actual machine, account, path and version read.
- Core service local is not every Agent's local machine. A Source snapshot is not automatically the current working tree.
- Mentioning a path in a message does not trigger copying, writes or Git operations. Work results belong in external files/repositories.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_sources, read_source, read_diff, read_file.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)

---
name: acs-project-context
description: Project, Root, Route and trusted caller context for ACS communication. Use when choosing a project, resolving contact visibility or continuing in another session.
---

# acs-project-context

## Knowledge boundary

Project identity and authorized contact scope; Native capacity and source files retain their own authorities.

## Core invariants

- Use the verified project_id and stable returned contact handles; names do not confer permission.
- Client, project Root and Route manager are management levels; ordinary collaborators are not another management tier.
- A new Native Session preserves Slot authorship and historical message relationships. Repository hints do not synchronize code.

## Retrieval map

Read only the reference needed for this question.

| Question | Reference |
|---|---|
| Current model | [model](references/model.md) |
| Decisions and limitations | [decisions](references/decisions.md) |
| Actual tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_projects, load_project, list_routes, list_collaborators.

## Application

Use the active schema and actual runtime evidence. The current source contract is `docs/runtime/COMMUNICATION.md` when that verified checkout is available. Read historical v6 material only for an explicit archive/transition question; it does not authorize or define current operations.

## Related knowledge

- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-web-collaboration](../acs-web-collaboration/SKILL.md)

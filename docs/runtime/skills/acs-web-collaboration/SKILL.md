---
name: acs-web-collaboration
description: Remote MCP, web SaaS Agent, ProjectContextPack, OAuth, HTTPS, secure Tunnel, plugin, filesystem SourceBinding, GitHub MCP coordination, and web Session capability knowledge for ACS. Use when a browser-based Agent manages or reviews ACS projects.
---

# acs-web-collaboration

## Knowledge boundary

Remote client context and access pathways. Project semantics belong to acs-project-context; security policy belongs to acs-policy-governance.

## Core invariants

- One global remote MCP connection can expose multiple Projects within the authenticated tenant and active service context.
- Web Sessions select project_id and load_project to obtain current Project context and source or workspace revisions.
- Owner private Tunnel access binds to the installation owner's trusted credential; OAuth HTTPS services validate their token and deployment rules.
- Remote Source access uses an admitted filesystem SourceBinding, external repository provider or both; current workspace and fixed revision views are distinct.
- Management, Review and execution tools use actual advertised capabilities; execution prepares the selected native environment.
- Notifications follow the active MCP Connection and Session; durable Project Inbox remains available after reconnect or Session replacement.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Web context and connection model | [model](references/model.md) |
| Choosing Tunnel, HTTPS and Source Provider paths | [decisions](references/decisions.md) |
| Web-visible tools and context loading | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: read_profile, list_projects, load_project, list_sources, list_files, read_file, read_diff, check_inbox.

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

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

---
name: acs-web-collaboration
description: Remote MCP, web SaaS Agent, ProjectContextPack, OAuth, HTTPS, secure Tunnel, plugin, filesystem SourceBinding, GitHub MCP coordination, and web Session capability knowledge for ACS. Use when a browser-based Agent manages or reviews ACS projects.
---

# acs-web-collaboration

## Knowledge boundary

Remote client context and access pathways. Project semantics belong to acs-project-context; security policy belongs to acs-policy-governance.

## Core invariants

- One global remote MCP connection can access multiple authorized Projects.
- Web Sessions use explicit project_id and load_project because local cwd and AGENTS discovery are absent.
- Remote source access uses an admitted filesystem SourceBinding, external repository MCP, or both.
- Web management and review are supported by read and governed mutation capabilities; execution depends on admitted Runtime capacity.
- Wake behavior follows observed Harness capability and Project Inbox remains the portable recovery path.

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

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

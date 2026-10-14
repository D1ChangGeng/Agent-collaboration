---
name: acs-web-collaboration
description: Remote MCP, web SaaS Agent, ProjectContextPack, OAuth, HTTPS, secure Tunnel, plugin, machine files, SourceBinding, GitHub MCP coordination, and web Session capability knowledge for ACS. Use when a browser-based Agent manages or reviews ACS projects.
---

# acs-web-collaboration

## Knowledge boundary

Remote client context and access pathways. Project semantics belong to acs-project-context; security policy belongs to acs-policy-governance.

## Core invariants

- One global remote MCP connection can expose multiple Projects within the authenticated tenant and active service context.
- Web Sessions select project_id and load_project for Root/Route instructions, knowledge indexes, active work and context completeness.
- Owner load_project reads current management files from the saved machine and directory or a single call's machine_id/management_path selection; documents beyond the inline budget provide read_file follow-ups.
- configure_project sets, replaces or clears saved management locations and document paths. An owner Project with an empty Source catalog can load its current management files.
- Owner private Tunnel access binds to the installation owner's trusted credential; OAuth HTTPS services validate their token and deployment rules.
- Owner machine tools operate on current files under the selected OS account through Local, SSH or Node; read_file requires path.
- filesystem_context and select_filesystem expose each MCP connection's machine/account/directory context; machine_id/cwd can select one call's target.
- Agents choose the work's source version through available native, Git or provider readers. Owner WorkItem source_baseline may be omitted or null, and eligible revise_work revisions can select, change or clear it.
- Historical Source readers select explicit source_id and revision; read_diff selects base_revision and target_revision. Shared deployments retain their original Source catalog and configured access.
- Review and acceptance record the inspected commit/tree and retain exact candidate/Evidence consistency, independent Reviewer and Finalizer authorization.
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

Relevant tools: read_profile, list_projects, load_project, configure_project,
filesystem_context, select_filesystem, read_file, list_directory, glob, grep,
write_file, edit_file, apply_patch, list_sources, read_source_file,
list_source_files, search_source_files, read_source, read_diff, create_work,
revise_work, submit_review, accept_work, check_inbox, read_message and
wait_for_response.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The product contracts are `docs/runtime/OWNER-RUNTIME.md` and
`docs/runtime/MACHINE-FILESYSTEM.md` in the verified ACS release or source
checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-source-evidence](../acs-source-evidence/SKILL.md)

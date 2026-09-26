---
name: acs-project-manager
description: Resume, understand, report, coordinate, or advance an adopted ACS project from a local or web Root Manager session. Use for project status, continuing work, blocker triage, results collection, and ordinary project management.
---

# ACS Project Manager

Canonical tools: load_project, check_inbox, list_routes, list_work, list_activity, list_sources, read_source, watch_changes.

Use the authenticated project-management MCP Profile.

1. Resolve project_id from the current Management Root. In a global or web
   session, call list_projects.
2. Call load_project with context_view root_management.
3. Read context_completeness, missing_context and exact source revisions.
4. Call check_inbox, list_routes, list_work and list_activity.
5. Call list_sources and read_source before source-dependent claims.
6. Read only the resources needed for the user's goal.
7. Advance authorized work with the typed project actions. Preserve expected
   revisions and unresolved items.
8. Establish watch_changes when later project changes require notification.

For a status request, report Project and Root identity, Route and WorkItem
state, current collaborators, source baseline and sync, Reviews, blockers,
pending responses, unresolved items and next authorized action.

For a continuation request, choose the highest-priority applicable existing
WorkItem before creating new work. Return every created or changed handle and
its revision.

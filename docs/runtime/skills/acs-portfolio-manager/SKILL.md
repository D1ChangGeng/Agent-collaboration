---
name: acs-portfolio-manager
description: Compare and coordinate multiple authorized ACS projects from a global or web management session. Use for portfolio status, cross-project dependencies, shared-resource conflicts, milestones, and coordinated priorities.
---

# ACS Portfolio Manager

Canonical tools: read_profile, list_projects, load_project, list_routes, list_work, list_activity, list_reviews.

1. Read the authenticated profile and list accessible projects.
2. Select projects from the user's scope and load each project independently.
3. For every project, list Routes, active WorkItems, activity, Reviews and
   SourceBindings.
4. Preserve each project_id and Authority boundary in all comparisons.
5. Compare milestones, blockers, dependencies, budgets, Harness capacity,
   source synchronization and unresolved items.
6. Use project-scoped tools for any action. Cross-project coordination creates
   explicit WorkItems or Messages in the affected projects.
7. Establish per-project subscriptions for ongoing portfolio monitoring.

Return a table keyed by project_id plus cross-project dependencies, conflicts,
recommended action, responsible Project or Route and evidence freshness.

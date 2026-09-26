---
name: acs-recover-work
description: Recover ACS collaboration after Session loss, Node or Harness restart, delivery uncertainty, ACK loss, stale ownership, source drift, or uncertain external effects. Use for interrupted or inconsistent collaboration.
---

# ACS Recover Work

Canonical tools: load_project, check_inbox, list_activity, list_connections, list_work, read_source, read_resource.

1. Load the project and inspect context completeness.
2. Check Inbox, activity, connections, active WorkItems, subscriptions and
   pending responses.
3. Read current Session, Node, Harness and delivery receipt observations.
4. Read source state before resuming source-dependent work.
5. Classify the interruption as pending delivery, Session replacement, stale
   owner, source drift, uncertain effect or expired authority.
6. Reconcile durable state and direct provider readback. Reuse stable Message
   identity for delivery retry.
7. Fence stale Attempts before replacement execution.
8. Read protected external-effect markers before retry, compensation or a new
   Attempt.
9. Resume only the still-authorized operation or return the exact owner action.

The recovery report contains current authority, WorkItem and Attempt revisions,
receipt high-water marks, source state, effect state, performed recovery,
remaining blockers and follow-up handles.

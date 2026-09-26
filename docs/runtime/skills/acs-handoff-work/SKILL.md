---
name: acs-handoff-work
description: Transfer an existing ACS WorkItem between Sessions, AgentSlots, roles, Routes, or machines while preserving source, evidence, messages, unresolved items, and acknowledgement continuity.
---

# ACS Handoff Work

Canonical tools: load_project, read_resource, read_source, list_evidence, list_collaborators, handoff_work, send_message, wait_for_response.

1. Load the project and read the current WorkItem revision.
2. Read exact source state: repository, branch, commit, tree, worktree, push and
   receiver-sync observations.
3. Read current Evidence, Artifacts, pending responses and unresolved items.
4. Resolve the destination collaborator and its current capability evidence.
5. Call handoff_work with origin, destination, source state, context handles,
   evidence handles, unresolved items and acknowledgement policy.
6. Send the handoff Message when the destination needs native invocation.
7. Track acknowledgement through Inbox and response state.
8. Report branch, base/head, worktree state, commit status, push status and
   receiver sync action.

A handoff changes responsibility while preserving WorkItem, Message, source and
evidence identity.

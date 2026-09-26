---
name: acs-delegate-work
description: Create or reuse ACS WorkItems and delegate goals to AgentSlots or eligible Harness capacity with durable asynchronous response tracking. Use for assignments, parallel work, specialist requests, and review delegation.
---

# ACS Delegate Work

Canonical tools: load_project, list_work, create_work, revise_work, list_collaborators, list_harnesses, configure_team, send_message, watch_changes.

1. Load the project and identify the target Route.
2. List existing work and reuse a WorkItem when its goal, baseline and accepted
   state match the request.
3. Create or revise the WorkItem with explicit goal, accepted state,
   constraints, source baseline, evidence contract, budget and deadline.
4. List collaborators and Harnesses. Configure the team only when the existing
   Scope bindings do not satisfy the work.
5. Send one Message per independently addressable assignment. Default to async,
   queue_until_idle and expected response.
6. For parallel assignments, retain one correlation group and distinct WorkItem
   or sub-work identities.
7. Establish watch_changes for review, blocker or completion events that matter
   beyond the direct response.
8. Return WorkItem, Message, response and subscription handles plus exact
   follow-up calls.

A delegation result states target AgentSlot, Harness evidence, delivery state,
source baseline, response condition, deadline and unresolved capacity gaps.

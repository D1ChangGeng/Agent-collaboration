# Collaboration decision map

Use configure_team when an existing Scope needs different collaborators,
duties or Harness requirements. In owner mode an ordinary member supplies
agent_slot_id, principal_ref, role and harness_requirements; the mutation also
supplies project_id, scope_handle, client_request_id and expected_revision.
Optional organization and Profile metadata describe the client and duties.
Shared mode applies its configured Grant, Policy and budget bindings.

Reuse a WorkItem when goal, accepted state, constraints and baseline still
match. Revise it when authorized intent changes. Create a separate WorkItem for
independently acceptable output or distinct ownership.

Delegation assigns new or selected work. Handoff transfers an existing WorkItem
and carries exact source state, evidence, unresolved items and acknowledgement.
Retain workspace view identity when the candidate includes local edits.

Use one Message for one addressable request. Independent requests keep distinct
WorkItem or sub-work identities and may share correlation. Owner messages can
remain valid through a disconnected Session; choose an explicit business
deadline when the goal itself requires one.

Select reviewers by exact candidate identity and verified independence.
Responsibility metadata helps assignment, while the recorded Review checks
establish eligibility for that candidate.

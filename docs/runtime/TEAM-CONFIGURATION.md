# Typed team configuration candidate

`configure_team` acts in an existing admitted Project Scope. Transport context
supplies tenant, principal and the active managing Grant. The command requires
`collaborators.manage`, `grants.manage`, an exact team revision and a deadline.

The live MCP `inputSchema` publishes these closed nested records:

- Member: `agent_slot_id`, `principal_ref`, `role`, `profile`, `grant_ref`,
  `permissions`, `expires_at`, `budget_ref`, `harness_requirements`.
- Policy: `policy_ref`, `rules`; rules contain `allowed_activations`,
  `allowed_delivery_policies`, `max_deadline_seconds`.
- Budget: `budget_ref`, `max_messages`, `max_pending_messages`, `expires_at`.

The transaction creates or updates AgentSlots, membership, child Grants, policy,
budget limits, events, Outbox and dedup. Child permissions are a subset of the
current managing Grant; child expiry cannot exceed the parent or its budget.
Budget usage survives reconfiguration. Removing a delegated member revokes its
Grant and Slot. The existing manager may join the team using its exact original
Slot/Grant/profile/permissions/expiry; that operation does not rewrite its Grant
or create a self-delegation.

Runtime schema 1.12 records Grant ancestry. Every Domain authorization checks a
bounded, cycle-free chain in root-first locking order. Revocation, expiry,
permission reduction or parent policy drift makes the child ineligible at the
actual protected boundary. Migration from the recorded 1.11 checksum adds the
lineage table while preserving prior Domain rows.

The configured team policy is part of the Scope policy snapshot already sealed
into delivery. Message admission and recovery enforce activation, deadline and
recipient budget. Reservations are committed with the original Message and are
not charged again on replay. The same check applies to direct Domain sends,
CLI and HTTP, as well as MCP. Reconfiguration changes the policy snapshot;
previously queued operations retain their old binding and must satisfy current
recovery checks rather than silently gaining the new policy.

`list_collaborators` observes effective Grant status. `list_harnesses` reports
registered endpoints and independently recorded native Session/Node bindings.
Absent native observations remain unknown and ineligible. Desired Harness
requirements in a team definition do not establish installed capacity.

Current verification is PostgreSQL, migration and component integration evidence.
Real Harness workflow Gates and independent Review remain required for a named
product support claim.

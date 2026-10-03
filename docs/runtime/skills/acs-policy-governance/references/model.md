# Policy and governance model

Organization or Tenant is the isolation boundary. Project scopes product data
and collaboration. Subject is a user, external AgentSlot or service principal.
Role describes responsibility. Grant authorizes permissions in a Scope. Policy
adds conditions. Profile filters tool discovery. Budget controls admitted use.
ApprovalRequest records an external decision requirement.

OAuth scopes communicate requested remote capability. The server still verifies
token issuer, audience, expiry, subject and scopes on every invocation.

Control metadata, Source, Payload, Artifact and Secret Reference have separate
authorization, residency, retention and audit boundaries.

## Organization and duties

Root/Route describe project/development-line responsibility. Task Agent is the
proposed collective term for explicit task responsibility. Engineer, Reviewer,
Specialist and Finalizer are duties. AgentSlot, Scope, WorkItem and replaceable
Session retain their own identities and cardinalities. Organization metadata
and combined duties remain descriptive; actual Grant/Policy/Profile checks and
candidate-specific reviewer independence apply. Finalizer decisions require
exact candidate/source/evidence/Review and effect/readback prerequisites.
The repository contract is `docs/runtime/AGENT-ORGANIZATION-MODEL.md`.

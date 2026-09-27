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

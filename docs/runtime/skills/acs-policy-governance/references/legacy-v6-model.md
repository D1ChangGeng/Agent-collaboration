# Policy and governance model

## Identity and access modes

Tenant is the isolation boundary. Project scopes product data and
collaboration. Subject is a user, external AgentSlot or service principal.
Trusted transport or enrollment supplies credential, tenant, principal,
Authority and incarnation. Typed handles resolve active objects in that
context.

A new single-owner installation records access_mode=owner. Owner operations
check active service and objects, explicit revocation, request deduplication,
expected revisions and operation-specific prerequisites. Role describes a duty
and team configuration records business members and Harness requirements.

Shared deployments apply per-subject Grants, Policy conditions, Profile views
and budgets. Existing configurations with unspecified access_mode retain
shared behavior until explicit migration. A legacy Grant reference can remain
as identity and audit lineage in owner mode.

## Actual protected boundaries

Explicit business deadlines apply when supplied. A Lease covers a concrete
resource gateway and its fenced operations. Candidate identity, Review
independence, hashes and deterministic storage govern result acceptance.

Remote transport validates TLS, registered keys, signed identity, Node
bindings and replay state. OAuth resource servers validate issuer, audience,
subject, scopes and token expiry. Token lifetime, business deadline and native
process readiness are distinct facts.

Control metadata, Source, Payload, Artifact and Secret Reference retain their
tenant, residency, retention and audit boundaries. Secret values stay in their
secret authority.

Historical recorded facts keep their original identity and digests after a
prior Grant's natural expiry. Explicit revocation controls new actions. The
owner product contract is `docs/runtime/OWNER-RUNTIME.md`.

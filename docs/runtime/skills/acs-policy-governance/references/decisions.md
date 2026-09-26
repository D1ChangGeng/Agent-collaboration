# Governance decision map

Grant the smallest Scope, operation, direction, duration and resource set needed
for the role. Use Profile filtering to reduce visible tools while retaining
server-side authorization.

Read operations still enforce Project and data boundaries. Mutations add stable
request identity, expected revision and deadline. Dispatch and protected effects
recheck current Grant, Policy, revocation, expiry and budget.

Acceptance and publication permissions remain separate. Cross-project action
requires authorization in every affected Project. Hosted, local and hybrid
deployment preserve one logical authority for each state domain.

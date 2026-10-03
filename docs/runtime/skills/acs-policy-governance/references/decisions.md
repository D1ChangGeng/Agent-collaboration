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


## Expiry and clock authority

Check Grant, command and Lease expiry against fresh PostgreSQL Authority UTC,
including after lock waits and at dispatch or protected effects. Sender,
receiver and native boundaries use a calibrated connection clock bound to the
same Authority incarnation and current Endpoint/Runtime/Node/boot revisions.
The upper UTC bound must be strictly before expiry. Refresh an overlapping
interval; unresolved uncertainty or an unavailable reference stops admission.
Uncertainty consumes the authorization window while the Grant expiry remains
fixed. Author new observation facts from fresh authenticated Authority UTC
samples and validate them against current Authority time. Calibrated interval
bounds govern validity windows. Re-reading a cached terminal fact preserves its
original timestamp and payload/hash.

Preserve canonical durable deadlines, aware wire signatures and hashes.
Monotonic durations govern live local budgets and leases; replacement requires
fresh calibration and Authority readback. Clock calibration sequence is audit
provenance. Durable command identity, nonce, generation, signatures and fencing
control replay and ordering. Presentation timezone is display metadata over the
canonical facts. The full contract is `docs/runtime/TIME-MODEL.md` in the
verified ACS Release or repository.

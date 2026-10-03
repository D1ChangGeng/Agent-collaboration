# Runtime model

Machine identifies a physical host. Node is the machine-side ACS service and
has boot/incarnation identity. Runtime is an admitted execution environment.
Harness is the external Agent product. Driver maps ACS lifecycle operations to
the native API. Session is a replaceable Harness context. Endpoint is a logical
delivery target. Attempt is one WorkItem execution try.

The Node owns local observations and journal. The Domain Authority owns
authorization and accepted state. Drivers report native facts and do not own
Policy.

Capabilities include operation, direction, scope, component versions,
credential scope, observed_at, expires_at and evidence. Unknown or expired
capability is unavailable for admission.


## Time and capability freshness

Capability and readiness timestamps are aware canonical UTC facts. Runtime
admission uses the authenticated Authority connection clock bound to the
current Connection, Endpoint, Runtime, Node boot and revisions. Its UTC
interval includes round-trip uncertainty and aging drift; freshness requires
the upper bound strictly before expiry. Unavailable or overlapping time
requires refresh or leaves the capability unavailable. New observation facts
use a fresh authenticated Authority sample; the interval's midpoint and bounds
govern freshness. Native readiness stamps the observation after inspection,
while expiry remains anchored to the pre-inspection earliest bound. Historical
cached terminal timestamps and hashes retain their original values.

Local durations, active execution leases and native idle TTL use monotonic
time within the current process. Replacements rebuild calibration and live
leases from durable Authority deadlines and fencing state. Audit snapshots
retain UTC bounds and reference/sample identity; monotonic values stay local.
Private/Tunnel deployment requires the Authority provider; isolated loopback
fixtures have a separate local test clock path.

Presentation uses an IANA timezone sidecar over canonical timestamps. Clock
sample sequence describes calibration provenance; command order and replay
protection use Domain revisions and durable signed receiver identity. The full
contract and evidence scope are in `docs/runtime/TIME-MODEL.md` in the verified
ACS Release or repository.

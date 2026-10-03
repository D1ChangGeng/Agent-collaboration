# Target-idle delivery candidate

The typed MCP `send_message` path commits `queue_until_idle` in the canonical
DeliveryPacket. Existing raw protocol callers retain the explicit `immediate`
mode unless they request queued delivery. Configured team policy is enforced
at the Domain boundary for either surface.

Queued invocation takes a target AgentSlot advisory lock through preparation
and native acknowledgement. Concurrent queued messages cannot both pass the
same idle observation and race their native calls. Busy, offline or unknown
observations retain the Message and prepared Attempt, record a retry time and
leave the native dispatch marker absent. Waiting does not spend another
DeliveryAttempt. The committed Provider workflow can retry the same identity.

The native Codex/OpenCode adapter reads the actual bound Thread/Session state.
A deferred Driver operation can be retried only while its journal has no
mutating I/O intent or dispatch. Binding changes, revoked authorization and
ambiguous native effects retain their existing rejection/reconciliation rules.

Remote queued delivery prepares the durable receiver Inbox and obtains a
separate signed `delivery.readiness` observation before admitting the Domain
dispatch marker. Each retry uses a fresh challenge and persists its signed
receipt. Idle observations have a two-second bound, checked against the
trusted Authority connection clock. Native readiness also has a transient
monotonic expiry and generation bound to its clock calibration. Sender and
receiver use calibrated UTC fields and strict upper-bound expiry checks.
Producer expiry is its earliest UTC bound before inspection plus the two-second
lifetime, capped by the operation deadline. A fresh Authority sample after
inspection supplies `observed_at`; inspection, calibration and producer
uncertainty consume the same window;
stale, uncertain or unavailable observations defer invocation before dispatch.
Clock uncertainty reduces the usable interval while the Grant and canonical
deadline retain their original expiry.

Calibration follows the authenticated Authority database reference and current
Connection, Endpoint, Runtime, Node boot and binding revisions. A replacement
requires fresh calibration and readiness. A gap between wall and monotonic
progression adds separate uncertainty, including on suspend/resume. Excessive
uncertainty or expiry overlap requests an Authority resample before trusting
cached freshness. Clock snapshots persist UTC bounds
and provenance; raw monotonic lease values stay in the current process.
Local loopback fixtures retain their isolated test clock path. See
[TIME-MODEL.md](TIME-MODEL.md) for the time and recovery contract.

Readiness is observation, not a native ACK or a model response. A post-marker
loss or an external native-state race remains uncertain and requires readback;
it is never converted into a blind retry. Native notification of completion
and the durable response handle remain separate from target-idle admission.

Current tests establish PostgreSQL/SQLite/TLS mechanics and structured Driver
behavior against declared protocol fixtures. Fresh real-Harness and ordered
Gate execution on the frozen source is still required.

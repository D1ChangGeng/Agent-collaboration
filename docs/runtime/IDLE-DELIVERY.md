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
receipt. Idle observations have a two-second bound; expired or unavailable
observations cannot authorize invocation. The configured clock-skew allowance
applies to future observation time, not an expiry grace period.

Readiness is observation, not a native ACK or a model response. A post-marker
loss or an external native-state race remains uncertain and requires readback;
it is never converted into a blind retry. Native notification of completion
and the durable response handle remain separate from target-idle admission.

Current tests establish PostgreSQL/SQLite/TLS mechanics and structured Driver
behavior against declared protocol fixtures. Fresh real-Harness and ordered
Gate execution on the frozen source is still required.

# Continuity and recovery model

Delivery records accepted_by_authority, target_inbox_committed,
runtime_dispatched, runtime_acknowledged and response_received as separately
observed facts. Missing layers remain unknown.

Outbox makes committed delivery retryable. Inbox makes content and recovery
durable. A response handle identifies the expected result. A subscription
identifies notification behavior. The active MCP Connection and Session
binding select immediate notification delivery.

Owner commands, Messages, registrations and tracking remain durable while the
service and objects are active. An optional business deadline can bound a
request. Shared deployments retain their configured authorization windows.
Caller wait timeout and internal transport timeout have their own meanings.

The owner stdio MCP entry maintains committed Message delivery through Temporal when
temporal_endpoint is configured. New installation records the selected local
provider port. A custom service that omits the setting retains pending Outbox
state for a separately operated dispatcher. Actual worker and receipt readback
establish dispatch, native acknowledgement and response. Recovery follows
persistent work intent across temporary remote and Temporal RPC failures while
management MCP remains available. Explicit revocation and a chosen business
deadline produce the affected Message's own terminal outcome.

Recorded terminal responses carry their original Dispatch and content digest.
Missing response bytes are copied to Core's matching Scope CAS through signed,
bounded delivery.readback chunks. Each chunk retains the Node/Dispatch identity;
Core validates offsets, bounds and the complete SHA-256 before storing the result.
Already copied historical results use that verified Core cache.
historical_responses retains fenced_late results with their original Attempt,
Dispatch, native outcome, timestamp and digest. Retrieve missing bytes by the
exact original dispatch_id. Current task state and receipt lineage retain
their separate identities.

Owner response reads complete their initial Project authorization transaction
before remote preparation, then perform a fresh authorized formal read.
Query, transfer and final read retain their applicable explicit revocation
checks. Inbox recovery preserves the same response and Artifact identities.

Idle native state admits invocation. Busy commits Inbox state and waits for
idle. Offline retains delivery for recovery with the current binding. Unknown
state requires actual inspection; reconnection or environment preparation can
restore readiness.

Session replacement preserves logical recipient, Inbox, response and
subscription identity. Native wake or push uses the actual client capability.
A later Session can discover and consume the same durable items.

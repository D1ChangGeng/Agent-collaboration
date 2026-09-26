# Delayed response and Human Bridge Runtime 1.9

Runtime schema 1.9 extends the receiver-owned 1.8 baseline. The only accepted
incremental predecessor is the LF schema blob with SHA-256
`b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614`.
An exact 1.9 schema is repeat-safe; an unexpected version or checksum fails in
the transaction. Setup and Workspace schemas are independent and unchanged.

## Delayed native response

`NativeResponseCollector` reads the immutable invocation through the existing
`NativeDeliveryAdapter` and calls only the bound Driver's `collect_result`.
It never invokes, resumes or steers native work. The first terminal observation
and stable native terminal timestamp enter the Node-owned SQLite response
Outbox. A retry reuses those bytes and the same projection ID.

`PostgresDelayedResponseAuthority` locks the original message, Attempt,
dispatch receipt and response receipt. It rechecks current Node enrollment,
binding revision and boot, WorkItem state, Grant, policy, accepted revision and
digest, current Attempt and database deadline immediately before projection.
An eligible observation commits `response_received`; a late observation is
retained as `fenced_late`. One projection may be consumed once. Exact command
replay returns the prior result, while another consumer is rejected.

Temporal's response workflow retries only the Node projection Outbox. Restarting
the client or worker keeps the same workflow and projection identity. It has no
native invocation activity.

## Incident-based Human Bridge

The authenticated recovery Surface exposes incident open/status/expiry, Human
request, automatic re-probe, manual receive and receipt confirmation. All
transports use the same `SurfaceCommand`, Domain context, scope Grant, command
dedup, operation, event and Outbox path. An incident opens only after a complete
bounded census of exhausted automatic paths. Re-probe, manual packet and normal
receipt identities retain the original message, operation, Attempt, dispatch,
accepted revision/digest and expiry.

`HumanBridgeProviderDispatcher` reads only a committed Human request Outbox row.
It publishes a digest-only notification through the POSIX local file provider,
then marks delivery only after exact file readback. Provider roots and child
directories are `0700`; journal, notification, sidecar and Inbox files are
`0600`, opened with `NOFOLLOW` semantics. Stable effect/provider Attempt IDs,
durable inode intents and bounded helper IPC make ACK loss repeat-safe.

`HumanBridgeManualInbox` treats an owner-only Inbox file as an observation, not
authority. It requires a trusted authenticated Surface command, reconstructs
Attempt/dispatch/scope fields from PostgreSQL, and submits the normal manual
packet command. Manual resolution requires the exact persisted normal receipt.
Actual human action remains `NOT_RUN`.

## Measured integrated evidence

The isolated a942 integration candidate ran an actual OpenCode 1.18.27
`opencode/big-pickle` response through `ReceiverNativeDeliveryBridge`, the
native Driver, Node SQLite, a deliberate first projection failure, restarted
Node/Core objects, an actual restarted Temporal worker and PostgreSQL. The
fixed response was observed, one `prompt_async` occurred, one response receipt
and one consumption committed, the Temporal Run identity was preserved and the
Windows Job reported no remaining process. The private evidence JSON is under
`integration_evidence/`.

Codex delayed model execution and actual user handling of a manual file were not
run. Windows rejects the local Human Bridge provider until a separate reparse
point and ACL implementation is reviewed.

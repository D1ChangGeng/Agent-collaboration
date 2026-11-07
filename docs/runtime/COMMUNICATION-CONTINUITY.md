# Communication continuity increment

This increment adds pure original-operation observation, wait-channel recovery
and Actor-scoped MCP hint continuity. It does not complete all WP04 management,
Native batching or cross-host qualification requirements.

## Original operation observations

`CommunicationDeliveryObserver(projects).observe(project_id, operation_ref,
credential, reconcile=True, expected_revision=...)` uses the same ProjectService
reader authorization and sender/recipient ACL as `read_message`. A manager does
not gain access to another pair's delivery facts by knowing its operation ID.
The expected revision is the receiver binding revision, not the delivery attempt
counter or team revision.

The observer queries only the original receiver/attempt. Current reader rights
and receiving selection are rechecked after provider I/O, including descriptor
failure paths. Actual positive ACK receipts may repair the Authority's technical
projection without creating an attempt, sending input, or adding an Agent reply.
A status string, missing operation or unknown Native result is not ACK evidence.

`LocalNodeEndpoint.reconcile_delivery` validates the existing SQLite invocation,
logical payload hash, Node/boot/Scope/Slot and dispatch marker. It calls only the
Native read/reconciliation port. Absent local markers stay uncertain; the method
does not manufacture evidence that a rolled-back journal never had an effect.

Remote `inspect_delivery` sends fresh signed **readback** requests while retaining
the original operation/attempt/dispatch IDs. This avoids permanently replaying an
old uncertain readback. Original signed prepare evidence is included with the
new ACK projection. `reconcile_marked` remains a distinct exact-request replay
mechanism and must not be used by a pure reconcile action.

## Wait reservation and selected result

Optional setting `wait_ingress_recovery` enables new reservations. Adopt
`communication_wait_schema.sql` explicitly through
`adopt_wait_ingress(connection)` after base project storage adoption. Startup only
verifies the independently versioned extension; it never creates its tables.

The extension stores operation/channel facts, not message bodies:

- A reply matching a live wait is **reserved**, with its original message,
  operation and reply relationships unchanged. Reservation is not a target Inbox
  receipt, Native ACK, or model-consumption claim.
- Before returning the selected ToolResult, the reader records **selected** and
  suppresses further Native activation. Possible existing Native markers remain
  untouched.
- Dispatch checks a reservation under the message lock, and final Native marking
  refuses a message already routed to the ToolResult/Inbox. Live renewed waiters
  defer it. An expired, genuinely unselected reservation with no possible Native
  effect releases the same operation to ordinary delivery.
- Cleanup is bounded and also runs in the default maintainer. Legacy active-wait
  receipts are never guessed to be unselected. Turning off new reservation writes
  still preserves the reader/dispatch fence for already-adopted reservation data.

The schema is separate from the base Project schema to preserve opt-in adoption
and old-client compatibility. It is part of the same PostgreSQL authority and
does not compete with Message/Inbox/Outbox or Native journals.

## MCP hints

Notification-session ownership now includes the actual authenticated address and
principal. Distinct trusted Slots sharing a principal cannot retire each other's
connections. Current matching Shared connections renew their observation lease;
retired or revoked connections are not revived.

Optional `notification_frontiers` uses the explicitly adopted
`communication_notification_schema.sql` extension, via
`adopt_notification_frontiers(connection)`. It records only the last message and
notice boundaries actually published per Actor/session/revision. Publication
reauthorizes the current binding immediately before emit; frontiers advance only
after successful transport publication and a current binding check. Failed sends
or acknowledgments retain the intent. In-memory state is bounded to two sequence
values per subscribed resource.

These are MCP resource hints. They do not mark read/consumed, prove model input,
or implement Native wake batching. A reconnect can rediscover Inbox history;
message bodies and explicit reply relationships are never merged or discarded.

## Peer identity

Configured remote adapters now bind their cache to committed endpoint,
connection, Node key, current Authority key, resolved sender public key and
trusted settings. Construction and health reads revalidate that source; absent,
changed, ABA or mode-mismatched candidates fail closed.

TLS health may return `acs-receiver-peer/1` and an opaque digest of the common
registered receiver context. It is not permission or an ACK. Missing legacy
identity is unknown, with no current Session claim; changed identity never
triggers preparation through the read-only inspection path. Transport request
and response use one bounded monotonic timeout and never automatically replay a
POST after an unknown ACK.

## Original-session cold restoration

Concrete Codex/OpenCode factories can opt into the signed lifecycle controller
with `lifecycle_control`, a pinned project catalog and explicit selected-account
reference. `lifecycle_message_wake` separately permits autonomous continuation
of a committed Message. Schema2 DriverJournal adoption and the initial private
capacity reservation are explicit operator actions. The initialization switch
can reopen an existing valid journal; it cannot recreate a lost journal in a
previously used namespace.

A stopped observation requires the original exclusive owned process identity,
birth and containment, a verified empty owned process tree/group, matching
profile/account/environment and an acknowledged original Native session. It
keeps input readiness and blockers unknown. A signed resume plan includes that
exact stopped-process reference. Codex launches only a replacement transport and
calls `thread/resume` for the original thread; OpenCode preserves its original
data roots and reads the original session through its new owned transport.
Neither path substitutes session creation or resends input.

After Node reconstruction, the factory also requires a retained full-stop
receipt, original journal/claim identity and the original Core-signed profile
plan, including archived Message lifecycle cycles. It does not adopt a process
by PID or name. Missing history, account/profile changes, uncertain creation or
unproved surviving descendants remain unavailable. Current Core enrollment and
execution authority are rechecked; an old permit supplies provenance only.

An uncertain input can reconnect only its same Native session for original-domain
reconciliation. It remains uncertain and blocks new input until a genuine
original ACK is read. A lost resume ACK never repeats transport launch.

When a known-ready receiver stops before the Message's Native effect, its same
Message/operation/Outbox can retain prior successful lifecycle frames and obtain
a fresh signed resume plan. This bounded history preserves the original capacity
digest and every possible-effect fact. It creates no replacement Message,
management operation or Agent reply. Core history also forbids namespace reset
after local storage loss. Explicit receiver rebind remains a separate authorized
CAS operation; it does not claim recovery of model working memory.

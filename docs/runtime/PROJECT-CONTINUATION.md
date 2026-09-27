# Project continuation and notification candidate

Message submission atomically records delivery, response tracking and its
notification preference. A bounded synchronous observation uses the same
durable response handle; replay does not resend the message. Waiting checks
the requested receipt itself rather than inferring missing receipts from a
higher marker. Terminal failure is reported separately from successful
receipt satisfaction, and timing out does not cancel tracking.

`watch_changes` records owner, targets, event kinds, delivery policy and a
PostgreSQL visibility snapshot. Projected Inbox events use a durable per-event
dedup ledger. An event whose ID was allocated early but committed later cannot
be skipped merely because a larger ID has already been observed. The snapshot
uses top-level `xid8` values, matching the semantics of PostgreSQL's
[transaction and snapshot functions](https://www.postgresql.org/docs/16/functions-info.html#FUNCTIONS-PG-SNAPSHOT).

PostgreSQL NOTIFY provides a commit-bound wake hint. The authoritative facts
remain in Domain receipts/events and the project Inbox; periodic reconciliation
covers lost hints and transient connections. Disabling a notification does not
delete the response or watched Inbox event. Owner consumption is idempotent.

The MCP resource `acs://projects/<project_id>/inbox` is authenticated and scoped
to the caller. Legacy MCP clients use `resources/subscribe`; the 2026 protocol
uses `subscriptions/listen`. A replacement subscribed MCP Session becomes the
current notification destination for that owner, and a retired Session cannot
reclaim delivery. Reconnection can receive a wake for an unconsumed completion;
its response handle and completion key remain unchanged.

The SDK tests verify proactive delivery over stdio and loopback HTTP, duplicate
suppression, reconnect recovery and supersession. The queued native delivery
mechanism is documented in [idle delivery](IDLE-DELIVERY.md). These are component
and integration results; native Harness automatic continuation, admitted web
ingress/consent and independently reviewed live Gate evidence remain outstanding.

## Delivered messages and Review requests

`check_inbox` returns bounded, cursor-based metadata for tracked responses,
delivered Domain Messages addressed to the owner's current durable Slots, and
pending Review requests explicitly assigned to that principal. Each item has a
typed handle and exact `read_message` follow-up. Incoming Domain Messages do not
require the sender to have used the MCP adapter. Actual request bytes are read
under current project/Scope authorization; metadata discovery does not preload
the content. Kinds and states narrow the page.

Message/Review consumption is owner-bound and persistent across Session changes.
Oversized reads roll back consumption. A consumed Review request remains pending
until the independent Reviewer submits an actual decision; reading never changes
evidence, acceptance or execution state. Current subscribed Sessions receive
wakes for unread incoming items, as well as completed tracked responses and
watched events. PostgreSQL channels are database-wide; notifications from another
schema are only irrelevant hints, never authoritative project events.

Native completed-response artifact-byte retrieval remains separate pending work.
The current response surface preserves receipt/reference evidence; it must not
claim the artifact contents were read when only a terminal receipt was observed.

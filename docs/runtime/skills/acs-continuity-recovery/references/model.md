# Continuity and recovery model

Delivery progresses through accepted_by_authority,
target_inbox_committed, runtime_dispatched, runtime_acknowledged and
response_received. Each layer is independently observed.

Outbox makes committed delivery retryable. Inbox makes receipt and recovery
durable. Response handle identifies expected result. Subscription identifies
future notification. Session activity is an expiring observation independent
from WorkItem state.

Idle admits invocation. Busy commits Inbox state and waits for idle. Offline
retains delivery for a current binding. Unknown waits for fresh observation.

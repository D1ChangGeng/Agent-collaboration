# Continuity decision map

Use async submission when the caller should continue after commit. Use sync
when it should wait for the target condition, normally response_received.
Omit caller timeout to wait for that condition or an observed terminal result;
supply a timeout to obtain pending handles early.

An owner Message's omitted deadline means continuous business validity. Supply
a timezone-aware deadline when the business goal has a latest useful time.
Shared mode derives or checks the horizon required by its configured
admission rules. Caller waiting preserves the Message and response tracking.

On disconnect, reconnect through the actual current Connection or Session and
read the Project Inbox. On busy state, queue until idle. On unknown readiness,
inspect and prepare before dispatch. Continue owner recovery according to
persistent work intent; Temporal RPC failures reconnect maintenance while the
management MCP stays available. Resolve explicit revocation or chosen deadline
expiry as the affected Message's terminal outcome.

ACK loss requires native readback and recovery with the same Message and
operation identities. Duplicate delivery converges on the prior receipt.
Replacement targets the current authenticated binding and preserves the
logical recipient. Use historical_responses to inspect a fenced_late result's
original Attempt/Dispatch, outcome and digest. Relate it to its recorded work
and evidence identity while current task state and receipts advance under their
own admitted Attempt.

Human Bridge is an incident recovery provider after eligible automatic paths
are exhausted. A manual return retains authentication, deduplication, expected
revision, revocation and any explicit business deadline; shared Policy also
applies. Classify pending delivery, binding replacement, source drift and
uncertain effects before choosing recovery.

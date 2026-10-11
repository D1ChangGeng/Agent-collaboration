# Send, wait and lifecycle time

New single-owner installations use `access_mode=owner`. Commands, Messages,
registration and result tracking remain durable while their service, identity
and target objects are active. A caller can choose an explicit business deadline
for a request. Shared deployments retain the configured horizons described
below.

| Time | Responsible component | Behavior |
|---|---|---|
| Owner business deadline | Calling Agent and Domain | Optional latest useful time for a command or Message |
| Shared Message horizon | Domain / Work budget / Scope Policy / Grants | Configured admission and result-application window |
| Harness execution control | Runtime and selected native environment | Governs the actual Attempt and its protected operations |
| Caller waiting | Calling Agent | Optional early-return duration; omission waits for the target condition |
| Internal operation timeout | Runtime adapters | Bounds one database, RPC, preparation, dispatch or retry operation |

## Submission and observation

`send_message` defaults to `response_mode=async`. It returns the committed
Message, response and notification handles. Durable dispatch and result
tracking retain their identities independently of that call. Owner stdio MCP service
maintenance dispatches committed Messages through Temporal when temporal_endpoint
is configured. New installation writes the selected local provider port;
custom configurations that omit it retain pending Outbox for their separately
operated dispatcher.

`response_mode=sync` commits the same Message, then waits for
`response_received` by default. `wait_until` selects a different receipt or
terminal condition. `wait_timeout_seconds` is optional; a nonnegative integer
limits caller observation and returns pending handles on timeout. Zero performs
one observation. Omission or null waits for satisfaction, a terminal delivery
result, caller interruption or loss of current read identity.

`wait_for_response` follows the same principle. `mode=any|all` and `until`
select the condition; optional `timeout_seconds` requests an early return.
An uncertain delivery remains recoverable and pending until a conclusive
receipt or terminal state is observed. Each observation checks current
identity and target state. Waiting releases the database transaction between
reads.

A cancelled MCP observation releases its wait worker and preserves the
committed Message and subscription. Client transport or Harness request limits
can also end a call. Retain the response handle and resume observation or read
the Inbox through the actual Connection and Session after reconnecting.

Response mode and waiting options are observation preferences for the same
submission. Reusing a `client_request_id` with changed wait preferences
observes that Message. Different canonical business input conflicts. Existing
command records retain their original digest compatibility.

## Owner business validity and result tracking

In owner mode, omit the business deadline on a command or Message to retain
continuous validity. A chosen deadline carries an explicit timezone and is
checked at the applicable admission, dispatch, retry and result boundary.
`business_deadline_elapsed` identifies an elapsed explicit command deadline;
`message_expired` identifies the Message's own elapsed business deadline.

A WorkItem schedule, a Message deadline and a read command retain their own
identities. Reading a persisted Message or response uses the current credential,
tenant, active objects and explicit revocation state. The Work schedule does
not become an automatic lifetime for those stored bytes.

The owner native result collector observes the original invocation until it
has a terminal response or the service stops. It preserves the native request,
Session and response identities. A read or transport failure enters recovery
with those same handles. Terminal bytes and receipts are stored with digests;
projection retries use the existing result.

Durable Inbox, response and notification state survives caller timeout and
client disconnect. Immediate notification uses the actual active MCP
Connection and Session capability. A later Session can use `check_inbox`.
Explicit identity or object revocation controls new actions.

## Shared business horizons

In shared mode the caller can omit `send_message.deadline`. ACS derives the
smallest horizon from Scope `message_ttl_seconds` (24 hours by default),
the Work budget's optional `message_ttl_seconds` or `expires_at`, current
sender Grant ancestry, and configured Team Policy, recipient Grant and Team
budget expiry. Policy and Work TTL start at canonical command issue time;
submission processing consumes that validity.

An explicit timezone-aware deadline can narrow the shared horizon. An expired
horizon or an override beyond it is rejected before commit. The receipt reports
the effective deadline. Shared dispatch and protected operations recheck
configured Grant, Policy, budget and expiry rules.

`create_work.deadline` bounds the creation command's admission. Work business
horizons belong to its explicit schedule or budget. Endpoint is replaceable
delivery capacity with current identity and binding checks.

## Execution control and source lifetime

Caller timeout changes waiting. `stop_attempt` targets a concrete native
Attempt and reports cancellation or termination at the actual Driver ownership
boundary. `cancel_work` records the separate Work decision. The ordinary POSIX
owner process supervisor proves its owned process group; containment claims
require the corresponding supervisor's receipt.

Registration identifies the intended Connection, Node, Runtime or Endpoint.
Execution reads actual process and native Session state, reconnects and
prepares the selected native environment when needed. An internal preparation
timeout bounds the saved preparation operation while durable work remains
available for recovery.

Current workspace Source reads return the admitted active view and its revision.
Named workspace or commit snapshots retain their exact bytes for Review.
Historical results and Review facts keep their recorded timestamps, source
identity and hashes after a prior Grant's natural expiry.

## Compatibility and verification

The typed send and wait surface preserves its receipt conditions, optional
caller timeouts and shared base schema. McpRuntime derives owner inputs from
the installed access mode. Existing unspecified configuration retains shared
until explicit migration. Reference Gate records retain their original
Profile, source and time-window evidence.

Runtime waits use process-local monotonic durations. Explicit absolute business
deadlines and shared windows follow the [time model](TIME-MODEL.md).
[Owner Runtime](OWNER-RUNTIME.md) defines owner access, native environment,
migration and evidence boundaries.

Component and database tests establish only the scenarios they execute.
Native Harness, service, cross-machine and performance claims require the
actual configuration's readback and measured evidence.

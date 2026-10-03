# Send, wait and lifecycle time

| Time | Owner | Behavior |
| --- | --- | --- |
| Message business expiry | Domain / Work budget / Scope Policy / Grants | Limits valid Message admission and result application |
| Harness execution budget | Runtime / execution Policy | Governs the native Attempt and protected execution |
| Caller waiting | Calling Agent | Optional early-return duration; omission waits for the target condition |
| Internal operation timeout | Runtime adapters | Bounds database, RPC, dispatch and retry operations |

## Submission and observation

`send_message` defaults to `response_mode=async`. It returns the committed
Message, response and notification handles. Runtime dispatch and response
tracking continue independently of that call.

`response_mode=sync` commits the same Message, then waits for
`response_received` by default. `wait_until` selects a different receipt or
terminal condition. `wait_timeout_seconds` is optional; a supplied nonnegative
integer limits caller observation and returns pending handles on timeout.
Zero performs one observation. Omission or null waits for satisfaction, a
terminal delivery failure, cancellation or loss of read authorization.

`wait_for_response` follows the same principle. `mode=any|all` and `until`
select the condition; optional `timeout_seconds` only selects an early return.
An uncertain delivery remains recoverable and pending until a conclusive
receipt or terminal state is observed. Each observation rechecks live access;
waiting holds no database transaction. A cancelled MCP call releases its
observation worker and preserves the committed Message and subscription.
Client transport or Harness request limits can also end a call. Retain the
response handle and resume observation or read the Inbox after reconnecting.

For new Message commands, response mode and waiting options are observation
preferences rather than submission identity. Reusing the same
`client_request_id` with changed waiting preferences observes the same Message.
Existing command records retain their original digest compatibility.

## Automatically derived business expiry

The caller can omit `send_message.deadline`. ACS derives the smallest horizon
from the Scope's `message_ttl_seconds` (24 hours by default), the Work budget's
optional `message_ttl_seconds` or `expires_at`, current sender Grant ancestry,
and configured Team policy, recipient Grant and Team budget expiry. Policy and
Work TTL start at the command's canonical issued time; submission processing
consumes that validity. An explicit aware UTC/offset-bearing deadline can
narrow the resulting horizon. An expired horizon or an override beyond it is
rejected before commit. The receipt reports the effective `deadline`.

`create_work.deadline` is the creation command's admission window; it is not
silently reinterpreted as permanent Work expiry. Work business horizons belong
to its budget. An endpoint is replaceable delivery capacity and has its own
current binding checks.

Business expiry and Grant revocation still fence authorized actions and late
result application. Caller timeout does not stop a Harness, shorten business
expiry, consume a subscription or change an Attempt budget. Use `stop_attempt`
for execution control and `cancel_work` for the separate Work decision.

## Compatibility and verification

The typed send and wait input contracts are revision 5. Explicit timeouts,
existing receipt conditions and explicit narrowed deadlines remain supported.
The changed MCP catalog is an explicit guided-upgrade boundary for existing
installations. Runtime waits use process-local monotonic durations; absolute
horizons follow the [time model](TIME-MODEL.md).

Tests cover virtual completion beyond 30 seconds, bounded pending responses,
worker cancellation, uncertain recovery, real PostgreSQL expiry derivation,
observation-only retries and live permission changes. Native Harness, service
and full cross-machine evidence retain the scope of the run that measured them.

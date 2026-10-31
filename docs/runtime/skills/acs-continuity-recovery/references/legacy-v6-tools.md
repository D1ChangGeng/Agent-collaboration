# Continuity tool map

- check_inbox discovers durable Messages, responses, Reviews and notifications.
- read_message reads or consumes Message and response content.
- watch_changes records event subscriptions.
- wait_for_response observes any or all targets until its selected condition;
  optional timeout_seconds returns pending handles early.
- set_notification changes notification delivery while preserving durable state.
- list_activity reads events and receipt lineage.
- cancel_work records the durable Work decision.
- stop_attempt controls one concrete execution try.

Automatic owner stdio MCP dispatch uses the configured temporal_endpoint. The
standard new installer writes the selected local Temporal address/port.
An unconfigured custom service retains pending Outbox for its separately
operated dispatcher. Read worker and receipt state before claiming dispatch.

send_message defaults to response_mode=async and returns committed Message,
response and notification handles. Sync waits for response_received by default;
wait_until selects another condition. Optional wait_timeout_seconds bounds
only the caller's observation. Zero observes once. Owner deadline is optional
and remains separate from these caller settings.

For an owner response handle, read_message and check_inbox prepare missing
terminal response Artifacts after their preliminary Project authorization
transaction has completed. Remote preparation uses signed delivery.readback
chunks bound to the original Dispatch and Node. Formal readback then checks
current access and the Core Scope CAS digest in a fresh transaction.

An already copied historical result reads from the verified Core cache.
Explicit revocation is checked at the applicable query, transport and formal
read boundaries. Terminal content and receipt facts retain their original
identities. Owner historical_responses exposes fenced_late results with exact
attempt_id, dispatch_id, native outcome and digest; transfer selects that
original dispatch_id. Current task and delivery receipts keep separate state.

Notifications follow the actual MCP Connection and Session. Native wake uses
the observed capability; Project Inbox remains available after disconnection.
Response tracking and subscriptions continue when a caller timeout or cancelled
observation releases a wait.

See `docs/runtime/OWNER-RUNTIME.md` for owner validity and
`docs/runtime/SEND-WAIT-LIFECYCLE.md` for receipt mechanics and shared horizons.

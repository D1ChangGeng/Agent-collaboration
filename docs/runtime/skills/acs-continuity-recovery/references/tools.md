# Continuity tool map

- check_inbox discovers durable Messages and notifications.
- read_message consumes Message or response content.
- watch_changes manages event subscriptions.
- wait_for_response observes any or all targets until satisfaction; optional timeout_seconds returns pending handles early.
- set_notification changes delivery while retaining durable state.
- list_activity reads event and receipt lineage.
- cancel_work ends the durable objective.
- stop_attempt controls one execution try.

Result follow-ups are executable and carry project_id. Native wake is used when
the Harness supports it; Inbox recovery remains the portable path.

Sync send waits for final response by default; async returns after commit.
Caller timeouts govern observation and preserve background tracking. Message
validity is automatically derived independently. The repository contract is
`docs/runtime/SEND-WAIT-LIFECYCLE.md`.

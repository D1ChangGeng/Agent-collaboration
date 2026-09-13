# Harness session binding and response projection candidate (Runtime schema 1.11)

This candidate introduces a PostgreSQL-owned, versioned native Harness session
binding for a WorkItem. The WorkItem retains its Scope and AgentSlot across
attach, replace and retire. Retired rows retain native session, version, receipt,
command and retirement provenance. The setup manifest and Route registry are
unchanged.

The authenticated external command surface accepts `harness_session.attach`,
`harness_session.replace`, `harness_session.retire`, `harness_session.read` and
`harness_session.result`. All target a `work_item` and use the binding head's
revision in `expected_revision`. Attach and replace require `binding_id`,
`scope_id`, `agent_slot_id`, `driver_kind`, `native_session_ref`,
`installed_version` and `receipt_ref`; retire requires `binding_id`. The result
admission requires `result_id`, `binding_id`, `native_session_ref` and
`result_ref`. These references are supplied as external evidence, not verified
by this Domain command.

`harness_session.manage`, `harness_session.read` and `harness_session.result`
are separate scoped Grant permissions. The active Grant, authority incarnation,
tenant, Scope, command deadline, WorkItem status and expected revision are checked
in the same transaction as binding changes. Command dedup, Domain event,
operation and Outbox are committed together. Readback returns the current head
and complete binding history. Result admission records `current` only for the
head's active binding; a retired binding records `fenced_late` and cannot become
a current result through this API.

The WorkItem's current AgentSlot row is locked and checked against its tenant
and Scope at each command boundary. A revoked Slot blocks new attach and replace;
result admission records `fenced_late`. An authorized read remains available for
history, and retire can clear an existing active pointer after Slot or WorkItem
revocation. The scoped Grant and active Scope remain required for those commands.
The command first reads the WorkItem Scope without a row lock, then locks the
Grant/Scope before the WorkItem and rechecks the Scope and Slot identity. This
matches the delivery path's lock order for concurrent commands on one WorkItem.

Migration from exact Runtime 1.9 is recognized by its integrated schema checksum
and adopts 1.11 through `DomainAuthority.initialize()`; schema metadata readback
must report 1.11. Exact 1.10 is also recognized for the versioned projection
extension. `schema_1_10.sql` and `schema_1_11.sql` are separate deltas. No automatic Harness
spawn, installed-version probe, driver attach or final Gate decision is implied.
This review revision supersedes an unaccepted 1.11 candidate checksum; it does
not silently rewrite a database already stamped with that older candidate.

For a native response, attach or replace may also seal an `attempt_context`
containing WorkItem, Scope, AgentSlot, Runtime, Delivery Attempt, Message,
Machine, Node boot, Node binding revision and delivery endpoint revision. The
Domain checks that context against the committed selected attempt and enrolled
Runtime. A historical binding without this context remains readable but cannot
advance `response_received`.

The Node collector verifies the actual Driver session and immutable Driver
binding against a `HarnessSessionProof`, then persists that proof in its SQLite
response Outbox. Projection requires a configured trusted Node Outbox readback
and compares the immutable stored observation to the submitted command before
reservation and again at the PostgreSQL commit boundary. `delivery.project_native_response` checks the proof against
the PostgreSQL binding row, selected attempt, enrolled Runtime, active Grant,
WorkItem, Slot, binding validity time and current binding head inside the projection transaction. A
retired binding can only record `fenced_late`; the `response_received` receipt
is written only for the active binding and current attempt. The projection
does not change WorkItem or AcceptedState. External Agents still decide when to
attach, replace and submit the projection command. Installed Harness version
and native receipt references remain external evidence; this candidate uses
fixture Drivers and does not claim a real Codex/OpenCode replacement Gate PASS.
Remote Node readback transport remains unmeasured; this candidate uses a
trusted local SQLite reader supplied by the host configuration.

Attach and replace save their committed Domain `attached_event_id` on the binding.
The Node proof carries that event ID; projection verifies its command, WorkItem
and revision against the Domain event. A missing event can be retained as a late
observation but cannot advance a receipt. Node and database wall clocks are not
used to establish attach-before-result causality. The final PostgreSQL transaction
uses `clock_timestamp()` to recheck Grant and command expiry, Node/Runtime
expiry and the current Scope policy digest. An expired Grant is denied before
Node readback; an expired Node/Runtime or changed policy fences the result.

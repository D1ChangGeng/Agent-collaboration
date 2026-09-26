# Harness session binding candidate (Runtime schema 1.10)

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
and adopts 1.10 through `DomainAuthority.initialize()`; schema metadata readback
must report 1.10. `schema_1_10.sql` is the isolated delta. No automatic Harness
spawn, installed-version probe, driver attach or final Gate decision is implied.
The existing `delivery.project_native_response` path does not yet consume the
new binding proof, so this candidate is not sufficient by itself to mark
P1-HARNESS-REPLACEMENT PASS.

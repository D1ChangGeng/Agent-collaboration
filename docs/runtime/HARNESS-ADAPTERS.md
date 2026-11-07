# Authenticated Harness Adapter 1

`runtime/harness_adapter.py` defines the async describe/observe/admit/reconcile
port. `SignedHarnessAdapter` implements it for the existing Codex/OpenCode Native
bridge and signed receiver service. `ReadOnlySignedHarnessAdapter` implements the
authenticated rejection/observation boundary for a receiver without a Native
input owner. Neither port creates tasks or Agent replies.

## Explicit Codex history contract

An operator-owned Codex 0.166.0 Native receiver may select
`history_mode="paginated"` in its factory settings. The Driver sends this only on
the new thread's `thread/start`, then requires the Native response to positively
report the same persisted `thread.historyMode` on start and resume. Omitted or
different readback is rejected. This option is limited to that reviewed Native
version; it does not admit Codex 0.166.0 into the restricted-version allowlist.

An omitted option preserves the existing Native selection and serialized profile
fingerprint. This is a trusted deployment setting, not a sender/message field.
The initial paginated thread may return the exact Native
`thread/turns/list` not-materialized-before-first-message error. Existing strict
first-input guards handle that state; unknown history errors and prior possible
input still block admission. No new history-error fallback is introduced.

## Trust and durable input

The constructor requires an existing `ReceiverService`, its existing
`ReceiverNativeDeliveryBridge`, a trusted current-binding provider and a current
binding-read authorizer. The read authorizer must enforce actual caller/project
visibility; management eligibility is not private-message read permission.
This is an in-process SDK port, not an additional unauthenticated HTTP listener.

The explicitly negotiated sealed format is `acs-delivery-admission/1`: base64
encoding of the existing JSON `SignedRequest` containing admission, body and
signature. The signature is verified by the existing receiver protocol. The
outer Adapter operation is the **Native invocation ID**, distinct from the Core
delivery operation. Recipient, message references, envelope digest and receiving
epoch must match the protected original.

`prepare_input` verifies the actual Native operation and records its current
generation/Session/auth lineage inside the existing Node-signed prepare receipt's
`evidence.adapter_receiver`. It does not spawn, resume or input. Replaying prepare
retains its original signed fact. A legacy prepare without that fact cannot claim
the new generation guarantee.

`admit_input` matches the outer command to that signed prepared generation, then
checks fresh, current-scope readiness under the receiver execution fence and
Driver lock. It enters `ReceiverService.dispatch`, retaining the existing durable
marker, boot fence, live Node/sender authorization and authoritative Domain marker
readback. The Native callback may return successfully only with an actual ACK.

A pre-existing dispatch marker causes original-operation reconciliation, never
a fresh Native call. Lost authorization or observation after dispatch produces a
typed unknown result with the original operation and possible-effect flag. An
expired admission still cannot prepare/dispatch; historical reconciliation instead
verifies the stored signature/identity and current read authorization.

## Real Native observations

Factory setting `record_handoff` is an optional strict boolean, default false.
When enabled, both actual receiver factories record handoff context and supply
`observe_native_input` through their existing lifecycle authorization callback.
The existing readiness and final Native input paths also check this opt-in input
lane; the check is not limited to the generic SDK.

The observer uses bounded, read-only APIs and exports classifications/digests:

- Codex validates status against the selected binary's generated schema and
  interprets actual `waitingOnApproval`/`waitingOnUserInput` flags.
- OpenCode checks the bound live `/doc` and `/config`, explicit session status,
  and schema-validated `/permission` and `/question` inventories scoped to the
  current Session. These two added HTTP paths are GET-only; reply/reject paths
  remain outside the allowlist.
- Actual process birth/containment readback and exclusive API ownership are
  required to establish a dedicated input lane. Attached sessions, stale data,
  missing inventory, schema mismatch and unavailable proof remain unknown.
- Native schema expansion permits only bounded acyclic local references and
  cannot fetch remote/dynamic schema references. No transcript, pending request
  body, credentials or configuration values are exported.

Schema/config fingerprints for an owner OpenCode environment may come from its
actual bound API rather than a nonexistent local schema/config file. Restricted
profiles still verify pinned schema/configuration. Current observations expire
after two seconds and cannot be replaced by a cached, apparently ready snapshot
from another Session/generation.

## Read authority and unsupported receivers

`AuthorizedObservation` retains the existing operation serialization fields but
is a distinct read capability. The production authorizer binds it to the
immutable original PostgreSQL invocation and current enrolled Node/Runtime/Slot.
It does not inherit the original sender's expired business admission or later
revocation. Current receiving Runtime/Node/observer revocation still rejects it.
Both Drivers reject this capability in every mutating action and Native RPC/HTTP
write path; it cannot start, resume, cancel or terminate work.

The read-only signed port verifies the existing signature/operation references,
never types into a terminal, returns unsupported before a new Native marker, and
retains unknown if an old marker exists. Without a Native reconciliation provider
it never turns a missing operation into definitive no-effect evidence.

## Qualification

The development report records actual Native probes separately from synthetic
wire peers, real signatures/SQLite/ACL, isolated PostgreSQL authorization and
independent model runs. A passing protocol test does not qualify every operating
system, Harness version, Shared profile or Orca host. The port and factory option
remain opt-in; production deployment and full client/UI readiness require their
own remaining development-pack gates.

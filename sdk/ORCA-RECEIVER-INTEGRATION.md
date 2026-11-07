# Trusted Orca Receiver bridge

`orca-receiver-port.ts` implements the four `OrcaReceiverPort` operations. It is a
bounded protocol bridge to explicitly supplied Core verification and Host
components. It owns no credentials, operation ledger, Native Driver, PTY or
transcript storage. Constructing it does not contact a Host or create a Session.

The concrete Python Core backend is `runtime.orca_receiver_backend`.
`ExistingOrcaReceiverBackend` verifies the original signed dispatch against the
existing prepared ledger, current authority and actual Host ownership.
`OrcaReceiverRouter` connects the existing prepare, readiness, dispatch and
readback operations to explicitly installed Host callbacks. Pass a trusted
`receiver_router_factory` to `ReceiverHTTPServer`; its backend must use that
server's exact Receiver service and ledger. It starts no ACS Native Driver.

The required Host extension must still be installed and qualified in actual
Orca. No public Orca API capability is inferred from these ACS components.
Missing observation, verification, atomic admission or original-reconcile
operations return `host_extension_required` for that operation. A configured
function does not establish a Native capability or an actual Host qualification.

## Required trusted dependencies

- `currentOwnership(receiverRef)` publishes the actual Orca-owned receiver,
  current Native Session five-tuple, binding epoch, actual Host principal and
  Core Authority/Scope. Its `ownerToken` must be the trusted registration/current
  child token. Equal-value registration replacement must replace that token.
- `authorizeHost` obtains an independent current Host grant for the exact
  operation/receiver/target Session. It returns the actual Host principal and a
  grant bound to all five NativeSessionRef fields plus the binding epoch, with a
  live synchronous `assertActive` scope check. An ACS bearer, sender, manager
  role, body flag or provider brand is not a Host grant.
- `ExistingSignedReceiverVerifier` must be an adapter around the existing ACS
  signed receiver verifier and prepared-operation storage. It is not a boolean
  assertion from a request. The bridge calls it with captured immutable command
  values and separately owned decoded signed bytes before Host admission.
- `OrcaAtomicReceiverHostExtension.admitVerified` must perform the final Core and
  Host authorization/readiness/current-child checks inside the Host's serialized
  handoff. Its `assertCurrent` callback includes current ownership, operation
  budget and the live Host grant. The extension must use it after preparation and
  immediately before synchronous enqueue. If enqueue occurred, later cancellation
  cannot turn it into a no-effect refusal.

## Existing Core verification contract

The negotiated sealed format is exactly `acs-delivery-admission/1`, containing
`receiver_models.SignedRequest { admission, body, signature }`. Its dispatch body
contains only `prepare_request_id` and `marker_receipt_id`. Original invocation,
message identity, Native Session/generation and auth revision must be recovered
from the existing prepared operation and its signed `adapter_receiver` fact.

The backing verifier must reuse the checks in
`ReceiverService._verify/_verify_identity`, current Core authorization,
`_prepared/_match_prepare/_check_current_boot`, signed prepared receipt validation
and the outer correlation performed by `SignedHarnessAdapter._admit` before its
dispatch. It must not call `_admit` as a verification shortcut that also invokes
the existing Native Driver. Do not invent a verifier-only RPC route or a second
receipt table. A standalone TypeScript Ed25519 check is insufficient: it would
omit prepared-ledger and current-authority checks and can disagree with Python's
canonical timestamp normalization.

The Python backend implements these checks without calling `_admit`. Before a
possible Host effect it records the exact verified command and sealed bytes in
the original dispatch receipt's `core_verified_input` evidence. This update
preserves its active execution lease. Normal ACK/unknown transitions preserve
that immutable evidence. There is no separate verification ledger or RPC.

`verifyDispatch` returns the verified original command, exact original Host/session
scope, existing verification reference and SHA-256 of the original decoded sealed
bytes. The latter correlates bytes; it is not a new signature or authorization.
`resolveOriginal` performs original identity/signature verification plus current
technical-read authorization. It must not reapply an expired sender deadline as
permission to hide an existing positive receipt. Reconciliation reads only that
original operation/dedup domain; it never calls send/admit or creates a Session.

## Pinned Orca source boundary

Inspected source: clean revision
`53fbfded41b8b0462d7ccd029475f89d12aa9bf5`. The scoped map is
`integration_evidence/acs-cross-harness-devpack-20261106/WP08_ORCA_HOST_PORT_MAP.md`.

`src/shared/agent-session/lifecycle/agent-session-mutation-envelope.ts` explicitly
ignores `expectedRuntimeFence`. Ordinary `agentSession.send`, stop, approval,
queue, model and conversation-command routes therefore cannot be substituted for
the required atomic original-generation entry point. No such fallback exists in
this bridge.

The implementation seam is
`structured-agent-session-input-handover.ts`: per-session serialization,
readiness/current-child validation, preparation, validation again, synchronous
enqueue. `structured-agent-session-send-compatibility.ts` can return journal
acceptance while native dispatch remains pending. Only actual settlement evidence
may produce an `accepted`/`queued` NativeAdmissionResult. Raw `ok`/`pending` replies
fail the existing result contract and become original-operation `unknown` after
Host admission may have begun.

The bridge preserves the original operation ID/epoch/generation after ambiguous
effects, loses no authoritative Host receipt, and performs no automatic replay.
Historical reconciliation can return the original generation's ACK while the
current receiver has another generation; that ACK cannot complete a new operation.
Neither Native receipt nor Host output creates an ACS `reply_to`.

For an uncertain original dispatch, the Python backend's `reconcile_original`
calls only the installed Host original-operation reader, outside Receiver SQL.
It validates the original operation/epoch/generation and rechecks current read
authority before settling that same dispatch receipt. Missing/unknown evidence
does not reenter admission. The router can run this lookup through the existing
readback route. An old-generation ACK remains attached to its old operation.

Host callbacks own independent Host authorization and serialized final admission.
Inside that handoff they must invoke `backend.assert_current(verified)` after
preparation and immediately before enqueue. Configure
`ReceiverHTTPServer(authorize_source_read=...)` with current enrolled-node read
policy independently of the original sender's input grant. The signed Core read
already delegates its currently checked message ACL; neither callback grants
transcript, control or user approval permission.

## Scope and evidence

The Node protocol tests use real Ed25519 signatures and explicit Host doubles.
Python tests exercise the actual Receiver verifier/ledger and original lookup.
`test_communication_remote_source_pg.py` composes actual Core PG/ACL, registered
TLS transport, the concrete backend/router and client provenance reads, including
a lost Host ACK and later current-session replacement. Host admission is still
an explicit double. `ORCA_HOST_QUALIFIED` and E5 remain false until an actual
Orca deployment is independently exercised.

Existing NativeView/Workspace delegate contracts remain available separately.
Rich Native controls and new destination-host binary attachment transfer are not
expanded here; v1.1 classifies binary attachment expansion as P2 optional. Existing
tested ACS attachment/draft functionality and its safety boundaries are retained.

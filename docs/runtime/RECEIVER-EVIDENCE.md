# Receiver evidence, Adapter contract 1

The first cross-Harness increment adds typed receiver observations to the existing
communication service. It preserves the message authority, trusted Client/Slot
bindings, authorization, explicit replies and Native delivery implementation.
The working ledger and measured environments are in
[`acs-cross-harness-devpack-20261106`](../../integration_evidence/acs-cross-harness-devpack-20261106/).

## Enable the read projection

The operator may add `"receiver_evidence": true` to an isolated SurfaceSettings
configuration. The default is `false`. With the option enabled, the existing
`list_harnesses` result includes a `receiver` object on each authorized item.
Both stdio MCP and authenticated Streamable HTTP use the same ProjectService
serializer and live authorization. This does not expose the development pack's
planned REST API.

Discovery and calls retain the existing project/Scope permissions. Receiver
readback cannot grant recovery actions; `allowed_actions` is currently empty.
Reading never prepares a receiver, admits Native input, marks messages read, or
creates an Agent reply. The catalog remains version 12 with unchanged inputs.

## Evidence and identity

- The existing PostgreSQL endpoint revision is `binding_epoch`. No duplicate
  receiving identity table is introduced.
- `provider_generation` binds the actual Driver binding, immutable Node/boot
  identity and native Session. Display names do not participate.
- Capability scope includes adapter/Harness versions, execution host, actual
  executable/configuration fingerprints, receiving epoch and generation. The
  configuration fingerprint also scopes the account, workspace, generated
  protocol schema and startup overrides without exposing their contents.
- Each capability separates `support` from `availability`. All 14 registered
  capabilities start as `unknown`; supported claims require evidence.
- Independent connection/process/session/input/blocker axes distinguish observed,
  inferred, unknown and unsupported knowledge. Terminal heuristics cannot become
  observed readiness.
- State readback expires after two seconds, anchored before the read. Slow I/O
  does not extend its validity. Scope changes, missing freshness and expired or
  future observations normalize to unknown.

The project projection checks the current machine, Node, boot and endpoint
revision, and checks the selection again after readback. It revalidates provider
DTOs through the wire serializer before returning them. Project authorization is
rechecked by the existing service before the response commits.

The Native adapters can prove a successful connection/session read and report
the actual input state. Their current read-only API does not prove process
liveness, absence of a human approval, or absence of a UI draft; those axes stay
unknown. `input_decision` is a conservative policy hint, never authorization to
execute or replay an input. Existing Native admission remains authoritative.

## Machine contracts

Runtime types live in `runtime/receiver_contract.py`. The generated
[`receiver-evidence.schema.json`](receiver-evidence.schema.json) and
[`receiver-evidence.ts`](../../sdk/receiver-evidence.ts) cover receiver snapshots
and Adapter admission commands/results. Result validation requires positive
evidence for definite outcomes and preserves `effect_possible=true` for unknown
Native outcomes. These types do not implement a second input endpoint.

Regenerate and check both artifacts:

```powershell
.venv\Scripts\python.exe tools/runtime/export_receiver_contracts.py
.venv\Scripts\python.exe tools/runtime/export_receiver_contracts.py --check
```

`runtime/harness_adapter.py` defines the integration port for later Adapter
admission/reconciliation work. Its Protocol declaration is not a support claim.
Old remote receivers without the evidence port return unknown capabilities;
they retain their existing communication behavior.

## Verification and adoption

The regression helper accepts an explicitly configured
`ACS_COMMUNICATION_TEST_DSN`, or the confirmed loopback-only ACS test container.
It rejects other database names and keeps credentials in the child environment.
Each database fixture creates and removes its own schema.

```powershell
.venv\Scripts\python.exe tools/runtime/cross_harness_verify.py `
  --test-container acs-communication-test-20261031 `
  --log integration_evidence/acs-cross-harness-devpack-20261106/receiver-tests.log `
  runtime_tests/test_receiver_contract.py runtime_tests/test_receiver_schema.py `
  runtime_tests/test_receiver_evidence_project.py runtime_tests/test_receiver_evidence_native.py
```

The installed-Native probe takes an explicit Codex binary, creates an isolated
CODEX_HOME, generates that binary's schema, starts one owned native Session,
reads it twice and closes its owned process tree. It does not inherit API keys
or production MCP configuration and requests zero model turns. Its evidence
class is `installed_native_protocol_no_model`, separately from synthetic Driver
peers and independently reasoning model exchanges.

This increment adds no database tables or migrations. Disabling the flag restores
the old projection; existing authors, message/reply records and request keys are
unchanged. Later durable input/event/client work requires its own explicit
adoption and recovery evidence. Core/UI contract readiness and Orca host
qualification remain separate, unfinished qualifications.


## Explicit lifecycle control mode

The Codex/OpenCode Receiver factories accept an optional `lifecycle_control`
boolean. The default is false. In control mode factory construction does not
create a Native Session; preparation and same-session resume require the signed
original Core recovery operation through the lifecycle executor. Ordinary
message delivery continues to use its original authority and Driver path.

The trusted factory settings must additionally contain an absolute
`lifecycle_catalog`, its exact `lifecycle_catalog_sha256`, and a private
`lifecycle_account_ref`. The catalog is the existing ProjectService catalog;
its bytes are pinned and bounded. The account reference is resolved privately
and only a digest enters capacity evidence. Request bodies cannot choose these
files, the account, the backend, or the signing keys.

For an explicitly new capacity only, `lifecycle_initialize_journal: true`
atomically creates a previously unused private namespace and adopts the existing
DriverJournal schema before any Driver claim. Its parent must already be private.
The flag is a one-time operator action; subsequent starts use false. Normal
control starts refuse missing storage or a legacy schema and do not migrate it.
The existing explicit adoption API remains the operator path for legacy journals.
A retained Core lifecycle plan for the same registration and Driver binding
prevents treating a lost entire directory as a fresh capacity. An existing
namespace is not recycled even if initialization fails or its journal is lost.

The corresponding trusted `remote_endpoints` entry also needs
`lifecycle_control: true`. The configured service installs the existing recovery
executor's transport; settings/key/registration changes invalidate older handles.
Disabling the flag refuses new lifecycle calls. This does not run a preparation
command as a side effect of discovery or reconnecting.

The same TLS-pinned Receiver listener exposes three fixed POST paths:
`/v1/lifecycle/observe`, `/v1/lifecycle/execute`, and `/v1/lifecycle/readback`.
Readback carries a fresh, independently signed Core request for the exact
original execution bundle. An old execution permit alone does not authenticate
a network read. Unknown possible effects are read back from the original journal;
they never authorize another Session or a retry of the Native effect.

`configure_team` commits configuration before lifecycle work and uses a stable
configuration preparation key. A Receiver without the fenced transport can only
report an existing session through read-only inspection; it reports preparation
as unsupported. Its old `prepare_runtime` callback is not invoked. Both paths
recheck current caller and exact committed receiving binding before returning.

Current Core callbacks can reuse one connection within a Node request. Each
current authorization check has its own committed transaction. No authorization
result is cached, and no SQL transaction survives into Native I/O. Local
file/claim checks run between the current checks that bracket capacity capture;
actual Native reads and effects retain the Driver's final current authorization.
Existing Native input evidence keeps its original expiry and is never extended
by lifecycle configuration. Fresh private reservation evidence has a separate
operator setting, `lifecycle_fresh_capacity_seconds` (default 15, integer 1-30).
The Core transport window is at most 30 seconds. Every execution recaptures actual
capacity and rechecks current Core/Driver binding before effects. Expired signed
observations are refused rather than extended.

These additions are opt-in development capabilities. The current evidence
separately identifies unit checks, actual local PG/TLS and controlled Native
responses. It does not establish a deployed Receiver, real Native/model or Orca
Host qualification. See the stage-agnostic evidence directory's current state.


Historical lifecycle ACK readback can reconstruct a Node controller over the
retained, claimed DriverJournal without recreating a pre-effect profile witness
or attaching a Native session. This grants historical metadata only. Preparation
still requires positive pre-effect capacity evidence. Missing original spawn
rows after a possible effect remain unknown and cannot attest absence. Expiry
before a permit is committed leaves the original deferred recovery operation.

## Continuing accepted lifecycle work

In auto maintenance mode, installed lifecycle transports also advance accepted
prepare/resume and ready-target rebind recovery operations. HTTP and stdio startup supply the operator's
ProjectService catalog; request profiles cannot replace it. External dispatch
mode leaves lifecycle execution to its external owner.

Scheduling uses a maintenance field in the same recovery Outbox payload. Short
transactions claim due rows with FOR UPDATE SKIP LOCKED, a random owner token,
actual Authority time and a default 180-second lease. A stale worker cannot
release a successor's lease. Two lifecycle jobs have an independent bound from
the four natural-message jobs. Retry delay is bounded from one to 30 seconds.
Corrupt due rows are paced without repairing their source or blocking others.

Pre-effect progress verifies the original accepted issuer/command and current
Grant/profile/Scope/binding through the same issuance and final Node fence.
It creates no external bearer, Message, task, attempt or new operation. Once
Native may have started, only original-journal readback is allowed under fresh
original-scope read authority. Removing runtime.invoke while retaining
runtime.read cannot turn that readback into a new execution admission.

No SQL transaction crosses Node I/O. Cancelling the awaiting scheduler cannot
stop a Native request already running in a thread, so its lease remains until
expiry. That thread may still record its authentic original outcome. Restart
preserves the possible-effect marker and therefore remains readback-only.

This deterministically progresses an accepted recovery intent. The separately
opted-in original-Message preparation path below uses the same lifecycle issuer
and Node journal, without creating a recovery command.

## Explicit ready-target rebind

`rebind_receiver` requires the original receiving endpoint's expected revision
and an explicit different `target_endpoint_ref` in the same Scope and stable
AgentSlot. Both endpoints require current management authority. Rebind also
requires `delivery.manage`, `runtime.read` and `runtime.invoke`; OAuth scope
restrictions apply at admission. The accepted command freezes the actual target
revision, source/target selection and current team revision/definition. A later
change cannot be silently adopted by retrying that command.

The target must already be prepared under its own explicit `prepare_receiver`
operation. Rebind uses the enrolled target's current signed lifecycle observation
and requires an existing ready Session, clear journal and no blocker. Fresh
capacity returns `lifecycle_rebind_prepare_target_first`. Busy, approval, draft,
unknown, invalid enrollment or expired evidence cannot publish a binding. Rebind
never issues a Native spawn/resume/input permit or calls execute/readback.

Publication is one Core transaction after Host observation. It rechecks the
original accepted issuer, current configuration and signed evidence; retires and
increments the explicit source endpoint; and gives the target an epoch above
both accepted endpoint revisions. An existing team member's endpoint preference
is updated while its roles, grants and other fields are preserved. Without a
configured member, the source and target must be the only active endpoints for
that Slot so retirement leaves one unambiguous receiver. Publication holds the
stable Slot lock as well as the endpoint/configuration locks to fence concurrent
endpoint insertion. Team configuration checks a requested endpoint after any
wait for that Slot lock. The original recovery
Operation retains its source receiver/epoch for audit; its evidence identifies
the separately published target epoch. Repeated request keys return that same
operation.

Messages, attempts, unknown Native outcomes and old receipts retain their
original endpoint/epoch. Rebind does not copy, replay or resolve them and does
not manufacture an explicit reply. New messages select the new target epoch;
old mutation admissions fail the current binding fence. Retained original
journals remain the authority for historical facts under read authorization.
This is a configuration capability; controlled PG/Node tests do not qualify a
particular installed Harness or Orca Host.

## Conditional preparation from an accepted Message

The sender's trusted `remote_endpoints` entry may set `message_wake: true` only
with `lifecycle_control: true`. The receiving factory separately needs
`lifecycle_message_wake: true` in control-plane mode. Both default to false.
The service also needs its installed ProjectService catalog. Missing policy,
catalog, signed capacity or qualified receiving capacity does not authorize an
unfenced `prepare_runtime` call. External maintenance mode retains its external
dispatch owner.

New natural Message commands seal the actual authenticated profile and issuer
context (without credential hashes) in their command payload. Wake authority
resolves the original Message/command/operation/Outbox/dedup/receipt/event lineage
and rechecks current message.send, runtime.invoke, profile and target binding.
OAuth Native sends additionally require the token's runtime.invoke scope;
message_only and Client inbox delivery keep their ordinary message scope.
Legacy Messages without that original source do not acquire fabricated context.

Technical preparation state lives under `receiver_wake` in that Message's own
`message.delivery` Outbox. It uses the actual Message operation and command IDs;
it creates no Recovery operation, second Message, task or alternate ledger. The
Driver's lifecycle journal still records a lifecycle suboperation, with no fake
Message/Attempt identity. Existing consumers keep the same packet/envelope and
22 P1 operations. Older Runtime writers that reject the new Outbox metadata
must fail closed; it cannot be silently stripped while an effect is possible.

Delivery's existing message/Slot serialization covers preparation. Fresh
capacity requires positive private-namespace/profile/claim/absence evidence;
existing ready capacity requires no new Native lifecycle effect. Busy, approval,
question, draft, unknown input or another unresolved original input/startup do
not start a replacement Session. Lost process/session evidence remains unknown;
this change does not qualify restoration of a stopped Native process.

An active reply wait retains its original ingress ownership. message_only never
enters this path. All bodies retain independent Message IDs even when initial
preparation is shared by subsequent ready deliveries. Core history includes
Message lifecycle plans when refusing recreation of a lost private namespace.

The possible-startup marker commits before Node I/O. A lost startup ACK permits
only readback of that same permit/journal, including after restart, disabling
new wake, loss of runtime.invoke, or Message expiry under current original read
authority. Terminal Messages with pending startup facts remain bounded readback
work; they do not reenter input admission. Message expiry and missing invoke
permission still stop actual input. An authenticated definitely-not-started fact
is retained; an independently ready receiver may later use ordinary admission.

Startup ACK is neither Message input ACK nor an explicit Agent reply. Only
ordinary Delivery admits the actual immutable input and records its own Native
receipt. Current evidence distinguishes actual Core/PG/TLS/Node/DriverJournal
with controlled protocol responses from real installed Harness/model/Host
qualification; the latter remains separate.

## Lifecycle observation and execution windows

A signed planning observation must still be fresh when Core issues its permit.
The permit has its own bounded transport window, constrained by the original
challenge, business deadline and current authority. The initial observation is
not renewed or substituted in the signed plan. Issuing a permit after that
observation expires is rejected.

Before entering the Driver, Node obtains a new actual capacity observation and
requires the same semantic profile/account, binding, owned process, Native
Session/generation, readiness and blocker state. The actual Driver lease is
bounded by this new current observation as well as the permit and business
deadline. Expired permits/current observations and changed targets or blockers
remain rejected. Native input observation lifetimes are unchanged. This avoids
spending a two-second Native state observation on the full Core/transport and
preflight round trip.

Current local Native evidence is scoped to Windows Codex 0.166.0 in explicitly
configured owner/native paginated-history mode. Actual isolated PostgreSQL,
enrollment/signatures, TLS, Node, Driver journal and Windows Job tests cover
creation, lost startup ACK readback, existing-ready preparation and same-identity
warm context resume, with one creation per case and zero model turns. The named
artifacts are under
`integration_evidence/acs-stage-agnostic-20261106/native-history-contract-20261107/`.
The standalone stopped-process empty-Session protocol evidence is separate from
production cold-recovery support; lost processes/sessions still retain unknown
capacity in production.

# Collaboration Runtime adoption contract

Status: accepted architecture and implementation authorization; Runtime support
is determined by the named Gate records. Contract revision: 2026-10-12.1.
The original adoption baseline is 2026-09-25.1; recorded Gates retain the exact
source, configuration and reference Profile they measured.

## Authority and inputs

The user-authorized upgrade instruction is identified by SHA-256
`0cffa4ab3888b3c05d61a72f0d7566dd9c03db07b4baffef29c9a6cbb7bb9e46`.
The original is retained in private bootstrap evidence. The accepted design
input is [the RFC package](../../RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/README.md)
at source baseline `a58c56c772d306cd5cef7cfca27deaf1ec240ebc`.
Original RFC files remain unchanged. This document records the adopted deltas
needed to apply that input to the current implementation.

The technical objective is P2 Cross-Machine Gate, in the order P1 local,
Codex-to-Codex across machines and sessions, Codex-to-OpenCode, then the public
MCP collaboration and continuation workflow. P2 Gate Review requires the
product owner's confirmation. P3 Hosted and P4 Ecosystem remain separate future
product decisions and evidence scopes.

## Owner Runtime

New single-owner installation records `access_mode=owner`. Trusted credential,
tenant/principal/Authority identity, active service and objects, explicit
revocation, request deduplication and expected revisions govern its operations.
Roles describe responsibilities. Ordinary team members supply AgentSlot,
principal, role and Harness requirements. The
[owner contract](OWNER-RUNTIME.md) defines these current product semantics.

Owner Connection, Node, Runtime and Endpoint registrations persist until an
explicit lifecycle change. Execution reads actual process and native Session
state, reconnects to the current binding and prepares the selected user's
environment. Native Codex and OpenCode use that environment's tools, MCP
servers, plugins, project configuration, provider, models and approval
configuration. Interactive native client handling is described below.
Attached Session read, send and cancellation follow the installed native API.
Process termination requires ownership evidence for the stopped object.

Trusted `SurfaceSettings.remote_endpoints` stores `endpoint_id`,
`authority_signing_key_ref`, `journal_generation`,
`old_boot_isolation_ref` and optional `prepare_argv`. Runtime readiness reads
the registered TLS-pinned target's `/healthz`. When preparation is needed,
the adapter executes the deterministic argument vector saved in that private
configuration and reads readiness again. MCP requests address registered
objects; the preparation command is an installation setting.

Owner commands and Messages remain valid by default while their service,
identity and target are active. An explicitly chosen business deadline can
bound a request. Async submission returns committed handles; sync waits for
the target condition with an optional caller timeout. Durable response
tracking and Inbox survive disconnect and caller timeout. With a configured
temporal_endpoint, the owner stdio MCP entry maintains already committed Messages
through Temporal. The new installer writes the selected local Temporal port.
An unconfigured custom service retains pending delivery for its dispatcher.
The owner native collector observes the same invocation until terminal result
or service stop.

Owner Source reads provide the current admitted workspace under its view
revision and retain fixed commit or workspace snapshots for reproducible
Review. Artifacts, hashes, deterministic storage, independent reviewer
assignment and candidate-specific acceptance checks retain their identities.
Historical execution and Review facts remain recorded after an earlier
Grant's natural expiry.

Shared is available for deployments with per-subject Grants, Policy and
budgets. An existing configuration with unspecified access_mode retains shared
behavior until explicit migration. Reference Gate isolation, version pins and
time windows remain facts of their recorded Profile.

## External Agent boundary

Root and Route describe external Agent responsibility extent. Engineer,
Reviewer, Specialist and Finalizer describe duties performed through explicitly
authorized AgentSlot bindings. Task Agent is their proposed task-level collective
term. Their reasoning, planning,
task decomposition, delegation, review selection and next-turn decisions remain
in the Harness. The Core executes submitted deterministic commands and records
authentication, authorization and command lineage. Provider recovery may resume
an already authorized operation; a new Agent turn requires an external command.

Management owns goals, constraints, engineering work packets, integration,
read-back and Gate decisions. Engineering owns Runtime implementation and
execution evidence. An independent Reviewer checks the sealed candidate. An
external Finalizer submits acceptance commands after the required evidence and
publication read-back. Agent self-reports create candidate evidence only.

## Adoption deltas

| Existing input | Adopted Runtime behavior |
|---|---|
| RFC WorkItem execution lifecycle | WorkItem acceptance is `candidate -> acceptance_ready -> accepted`. Execution progress, waiting, failure, cancellation and effect/publication are separate dimensions. |
| Optional direct acceptance profile | This upgrade requires independent review of a sealed candidate, integrated-baseline tests, and Finalizer checks. |
| RFC first Harness examples include Claude | P1 delivers Codex and OpenCode Drivers. P2 first proves Codex-to-Codex; OpenCode follows as a separate Gate. |
| Setup-only manual relay contract | The existing setup profile retains its explicit relay rules. Runtime bindings use `desired=system_managed_e2e`; Human Bridge is a bounded recovery incident. |
| Setup observations live in Harness context | Runtime observations have Scope, version, provenance and applicable freshness. Owner registrations persist and readiness is inspected at execution; shared Profiles retain configured windows. Node supplies observations and Domain owns the projection, independently of setup metadata. |
| Minimal Workspace schema 0.3 | Preserve Root, Route and knowledge metadata. Add opt-in Runtime schema separately, with PostgreSQL as the domain authority. |

The setup Skill remains an installer/configurator. Its release version,
Workspace schema, Runtime package version and Protocol version are separate.
Installing metadata never enables background execution, remote trust, hosted
storage or source export by implication.

## Required mechanisms

### Domain and authorization

Use one logical PostgreSQL authority per domain, with `authority_id`,
`authority_incarnation` and `home_location`. In one transaction validate
trusted identity, active service and target Scope, explicit revocation,
canonical request input, expected revisions and operation prerequisites.
Apply the transition, append event and Outbox, and persist dedup.
Emit `accepted_by_authority` after commit. Reusing an idempotency key with
different canonical business input is a conflict.

Owner admission applies those checks continuously and checks a business deadline
when explicitly supplied. Shared admission additionally validates per-subject
Grant, Policy version, configured expiry and budgets. Real resource gateways
and acceptance operations retain their specific prerequisites in both modes.

Authenticated subject and tenant come from trusted transport/enrollment.
Body fields address an object and carry request data. Send, invoke, Source
read/write, publish and accept retain their operation identities and audit
lineage. Dispatch and retry recheck explicit revocation, target state and any
applicable deadline or shared governance. Recovery preserves the original
command lineage and scope.

Shared admission windows and explicitly bounded owner operations use an
authenticated Authority connection clock at sender, receiver and native
boundaries, bound to the current Authority incarnation,
Connection, Endpoint/Runtime/Node revisions, boot and journal generation.
Monotonic round-trip calibration supplies a UTC estimate with explicit
uncertainty; admission requires its upper bound strictly before expiry and
refreshes an overlapping interval. Unavailable or uncertain time stops
admission. Private/Tunnel deployment requires the bound Authority provider.
The Domain reads fresh PostgreSQL UTC before and after locks; final native
Domain checks use that reference with strict expiry. Authored observation facts
use a fresh authenticated Authority sample, while deadline and freshness decisions
use the calibrated UTC interval. Cached terminal facts retain their recorded
time. Explicit revocation, revision and protected gateway checks apply in both
modes; Grant and permission checks retain their shared Profile boundaries.
Local duration uses monotonic time, while durable deadlines and evidence
remain canonical UTC. Presentation uses an IANA timezone sidecar. Existing
aware wire signatures and hashes remain compatible. See
[TIME-MODEL.md](TIME-MODEL.md) for calibration, recovery and evidence scope.

Scope, Root, Route, AgentSlot and WorkItem identity survive Machine, Node,
Runtime, Session, directory and transport changes. Keep versioned ScopeBinding
and HarnessSessionBinding distinct; retain retired binding provenance.

### Delivery and durable operations

Messages retain logical `message_id` through retries and Provider changes.
DeliveryAttempt records Connection, selection revision, optional business
deadline and errors.
Inbox dedup checks command/message identity, target Scope, accepted revision and
preconditions. Packet includes goal, accepted state, request, constraints,
source baseline, context/artifact digests and expected evidence/response.

Record the layers independently:
`accepted_by_authority -> target_inbox_committed -> runtime_dispatched ->
runtime_acknowledged -> response_received`. Missing evidence remains unknown.
Evidence, effects, review and acceptance have their own records and read-back.

Temporal is the first Durable Operation Provider. Its workflow history owns
operation execution records; PostgreSQL owns Task/Lease/Inbox/Outbox/acceptance.
Use Outbox dispatch, idempotency and reconciliation across the transaction/RPC
boundary. Actual Temporal Server and worker recovery are required for P1.

Machine Node owns a SQLite observation journal, boot/incarnation, durable local
mailbox and process observations. Reconcile uncertain spawn with operation labels,
process tree and Provider read-back. Node never becomes a competing Domain writer.

### Drivers, surfaces and routing

Drivers map spawn, attach, invoke, resume, cancel, terminate and inspect to
versioned native APIs, ACP or structured CLI. They return actual structured
observations; Domain owns admitted transitions. Owner native profiles resolve
the selected user's current binary and configuration at preparation time.
The factory can accept a compact environment selection and derive its current
version and available schema/configuration observations. Codex uses the
selected config's approval_policy. Interactive server requests use the
Driver's server_request_handler hook into JsonRpcClient. The standard headless
Receiver factory leaves that hook unconfigured and the transport replies
-32601 to a server request. An interactive integration needs its actual client
handler, authorization decision and native response readback. Approval
configuration and request-handling capability are separately reported facts.

Conformance exercises the actual installed Codex or OpenCode API and records
its version and results. Reference Gate Profiles retain their recorded version
pins, restricted launch settings and native multi-agent disablement for the
specific independence scenarios. Candidate reviewer independence remains a
separate identity and assignment check in owner mode.

P1 Harness replacement preserves the no-model HarnessSessionBinding component
as component evidence and requires a same-run live corollary: an owned OpenCode
process creates one idle native Session, replaces it with a second directly
read-back Session, and sends the single budgeted model request only through the
replacement. The formal scenario is `live_composite`; neither half is promoted
outside its recorded scope.

MCP, CLI and versioned HTTP invoke one Domain service and schema. Validate actual
entry points, including unauthorized and duplicate commands. A2A is an optional
Gateway and ACP a Driver boundary, not alternative Domain authorities.

The public P2 MCP surface is defined by
[P2-MCP-WORKFLOW-CONTRACT.md](P2-MCP-WORKFLOW-CONTRACT.md) and
[P2-MANAGEMENT-WORKFLOW-CONTRACT.md](P2-MANAGEMENT-WORKFLOW-CONTRACT.md).
The final collaboration-control parity supplement is
[P2-CONTROL-PARITY-CONTRACT.md](P2-CONTROL-PARITY-CONTRACT.md); it follows both
workflow Gates and precedes P2-REVIEW. A documented Gate requirement does not
claim that the current MCP catalog or a Chat Host already implements it.
Global installation is project-independent; project adoption records one stable
project_id in the Management Root AGENTS block and machine manifest. Every
project-scoped runtime tool carries that ID.

The single-user ChatGPT private Tunnel binds the local stdio MCP process to
the installation owner's trusted principal and configured access mode.
Recorded P2 reference runs retain their original Grant and Profile bindings.
The Tunnel trust and test boundary is
[P2-PRIVATE-TUNNEL-PROFILE.md](P2-PRIVATE-TUNNEL-PROFILE.md). The remote HTTPS
resource-server profile retains its OAuth binding contract.

Root Agent is an external Session project-responsibility projection, while Project, Root, Route,
Scope, AgentSlot and WorkItem retain durable identity. Local Sessions obtain
project context from the Management Root. Web Sessions use list_projects and
load_project through remote HTTPS MCP or an admitted Tunnel.

The typed surface covers project context, Route and WorkItem management, team
configuration, Harness and Source discovery, messaging, waiting, Review,
acceptance, subscriptions and protected control. Owner configure_team stores
AgentSlot, principal, role and Harness requirements in an existing Scope.
Shared configuration also applies Grant, Policy and budget bindings.
send_message commits response tracking and notification atomically. Async is
the default; sync waits for the same response handle's target condition.
Caller waiting has an optional timeout.

The machine catalog preserves its shared base required/optional lists and
Profile support table. McpRuntime exposes the installed mode's input schema:
owner makes business deadline optional, allows ordinary Team members,
makes configure_team policies/budgets and create_work budget optional,
and permits current workspace reads with an omitted Source revision.

The setup Skill owns guarded installation and migration procedures. Runtime
Skills are metadata-routed knowledge modules for ACS entities, authority,
invariants, decision axes, evidence boundaries and tool implications. The
Harness loads one applicable Skill and one named reference at a time, while
ProjectContextPack and project sources provide current facts. Domain Command
remains the deterministic internal protocol and submit_command remains an
advanced Profile tool.

### Review and product-capability boundary

Independent Reviews prioritize the implemented architecture and product
behavior visible through the Runtime. They inspect authority transactions,
authorization, revisions and fencing, durable recovery, Node and Driver
read-back, Harness lifecycle behavior, cross-Harness or cross-Machine flows,
and user-visible results from representative fault paths. Each conclusion is
bound to the exact source, runtime identity, receipts, read-back and cleanup
evidence that supports it.

Evidence integrity, applicable freshness, validator scope, candidate-specific
reviewer identity and independence, and current acceptance identity remain
mandatory prerequisites. Recorded historical facts retain their original
provenance after a prior Grant's natural expiry. They establish whether a claim
is admissible; they do not replace evidence that the implementation performs
the promised product capability. Component-only, fixture-only, no-model,
single-normal-delivery and offline-completeness results retain their narrower
scope until the corresponding live behavior is read back.

Directed CommunicationBinding resolves an authorized DeliveryPlan: addressing,
message, activation and receipt providers plus policy constraints. Candidate
selection uses observed capabilities and a bounded recovery budget. Human Bridge
requires exhaustion of eligible automatic recovery, a still-valid task and an
incident with attempted paths, evidence, expiry and recheck/exit conditions.
Successful re-probe returns to an automatic path. Late manual packets undergo
the same dedup, deadline, revocation and accepted-revision checks.
Normal transport receipts can resolve a manual path only when their immutable
evidence contains the exact Human Bridge incident, generation, packet,
direction and payload binding, or when an already committed `completed` native
terminal receipt is reused on the exact Message, Attempt and Dispatch with an
exact evidence digest. Other matching Message/Attempt receipts remain unrelated
and are rejected.

### Protected resources and acceptance

A Lease binds its owner Attempt, Runtime, concrete Resource, mode, Authority
incarnation, generation, fencing token and applicable expiry. Shared resource
admission also applies its configured Grant and budget. Test stale-owner
rejection at the real Effect/Resource gateway after replacement. The lock and
proof cover the named gateway and its fenced operations.

Native tools use the selected user's environment and approval configuration.
Interactive approval depends on the native client handler described above.
The ordinary POSIX owner supervisor reports owned_process_group with
subtree_containment=false. Process stop evidence covers that actual ownership
scope; stronger containment requires the corresponding supervisor and readback.
Parallel Engineers can use distinct worktrees. A resource that cannot fence a
replaced owner requires confirmed isolation or stop before reuse.

An external effect with an ambiguous result enters `uncertain`. Read back the
marker/result before adopting, compensating or authorizing a new Attempt. Partial
artifacts, stale baselines and unresolved protected effects cannot pass acceptance.

Execution evidence includes baseline and workspace view revision, output
commit/tree/diff/untracked manifest,
tests and exits, toolchain/OS/lockfile, artifact digests, actual usage or explicitly
unknown usage, source sync and unresolved items. A changed integration baseline
invalidates affected evidence. Hashes prove integrity, not the truth of a claim.

Acceptance order is: parallel implementation; seal candidate; independent
review; integrate candidate; test integrated baseline; mark acceptance-ready;
freeze final surface; authorized publication; actual read-back; postflight;
commit AcceptedStateRevision. Its immutable revision records accepted_by,
policy_version, parent_revision, scope, source/evidence/readback references,
unresolved items and validity range. Publication and accepted state are separate.

## Data and migration

Control Metadata, Source, Payload, Artifact and Secret Reference have independent
authorization, residency, retention and audit boundaries. Keep secret values out
of packets and logs. The local profile uses authorized source workspaces and
project-private test resources. Runtime adoption does not configure host autostart,
public listeners or Hosted storage.

Inventory Root/Route/project files, AGENTS, knowledge, source relationships and
external Session references with digest and provenance. Dry-run before adopting.
Preserve existing identities and original bytes; imported observations retain
their imported/endpoint_reported/unverified labels. Schema adoption, execution,
enrollment and data export are separate switches. Shared authority cutover
uses its drain/checkpoint/export and Grant revocation procedure; rollback
retains new durable state and audit facts.

Explicit private owner adoption verifies the stored credential, preserves
identity and a configuration backup, and clears natural expiry on active,
nonrevoked identity and registration records. activate_owner_mode applies
that Surface/database transition. Revoked and retired objects retain their
lifecycle state.

Receiver process deployments retain their own mode and signed configuration.
An existing unspecified process config remains shared. Receiver owner/native
migration constructs a matching Runtime/factory configuration and deployment
digest, uses the original Node key to sign the next Endpoint registration,
commits that revision with its expected prior revision, and restarts with the
matching process config. Read back the Endpoint digest/revision, actual mode,
Session and readiness. Preserve the original profile, credential, keys and
Node identity for recovery.

## Validation and claims

Named Gate evidence retains its original baseline, access mode, reference
Profile, version pins, time windows and measured scenarios. Current owner
behavior requires evidence for its actual configuration. Documentation updates
preserve historical results and their scope.

`tools/bootstrap/audit_setup_baseline.py` records setup-only fresh-process evidence and
preservation inventory. Runtime Gate scenarios are defined in
[gate-contract.json](gate-contract.json). `tools/runtime/validate_gate.py` checks evidence
completeness and digests; a passing validator is not an independent runtime test
or authorization to accept/publish.

P1 independent Review attachment requires two consecutive audits after every
mandatory scenario has passed. Each audit writes an immutable numbered receipt
with its authenticated input state, exact input manifest and candidate-scoped
postflight. The next audit's input manifest must close the prior receipt, and the
current run manifest must close the latest receipt. Both receipts must bind the
same unchanged candidate-file digest; command output alone is not audit proof.

Every passing scenario binds source baseline, Machine/Node/OS, Core/Provider,
Driver/Harness/database/protocol versions, Credential Scope, Direction, Policy,
expiry, scenario and command/operation/message/event IDs, receipts, raw output,
fault injection, source/artifact/effect read-back and recovery trail. Use explicit
not-applicable reasons only where the scenario does not exercise a layer.

`supported` additionally requires explanation, decision logic, real mechanism,
invariant verification and representative E2E evidence in the same named Profile.
Tests with fakes remain unit/fixture evidence. Two processes on one host do not
prove dual-machine support. Bootstrap SSH or native Codex messaging does not
prove Collaboration Runtime delivery.

P2 completion requires P2-MCP-WORKFLOW, P2-MANAGEMENT-WORKFLOW and
P2-CONTROL-PARITY before P2-REVIEW.
Representative evidence includes real Codex and OpenCode clients, a remote
web-capable MCP client, explicit project isolation, local and web context
hydration, the recorded Profile tool view, Source reads, asynchronous messaging
and the reference Profile's bounded synchronous scenarios, Session-aware
notification, Review, Inbox recovery and
metadata-first Skill routing, selective reference loading and Project context integration.

## External source reference

Codex App Server is an official structured integration surface for clients.
Driver implementation must bind observations to the installed version; the
documentation alone cannot establish deployment conformance.
[Official App Server documentation](https://learn.chatgpt.com/docs/app-server)
(retrieved 2026-09-11).

## Organization and responsibility vocabulary

Root and Route describe project and development-line responsibility. Task Agent
is the proposed task-level collective term; Engineer, Reviewer, Specialist and
Finalizer describe duties. The separate entity, binding, authority and candidate
independence rules are in [the organization model](AGENT-ORGANIZATION-MODEL.md).

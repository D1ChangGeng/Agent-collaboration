# Collaboration Runtime adoption contract

Status: accepted architecture and implementation authorization; Runtime support
is determined by the named Gate records. Contract revision: `2026-09-11.1`.

## Authority and inputs

The user-authorized upgrade instruction is identified by SHA-256
`0cffa4ab3888b3c05d61a72f0d7566dd9c03db07b4baffef29c9a6cbb7bb9e46`.
The original is retained in private bootstrap evidence. The accepted design
input is [the RFC package](../../RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/README.md)
at source baseline `a58c56c772d306cd5cef7cfca27deaf1ec240ebc`.
Original RFC files remain unchanged. This document records the adopted deltas
needed to apply that input to the current implementation.

The technical objective is P2 Cross-Machine Gate, in the order P1 local,
Codex-to-Codex across machines and sessions, then Codex-to-OpenCode. P2 Gate
Review requires the product owner's confirmation. P3 Hosted and P4 Ecosystem
remain separate future product decisions and evidence scopes.

## External Agent boundary

Management, Route, Engineer, Reviewer, Specialist and Finalizer are external
Harness Agents or explicitly authorized AgentSlots. Their reasoning, planning,
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
| Setup observations live in Harness context | Runtime observations have scope, version, expiry and provenance, with Node as observation source and Domain as projection authority. They do not enter the setup manifest or Route registry. |
| Minimal Workspace schema 0.3 | Preserve Root, Route and knowledge metadata. Add opt-in Runtime schema separately, with PostgreSQL as the domain authority. |

The setup Skill remains an installer/configurator. Its release version,
Workspace schema, Runtime package version and Protocol version are separate.
Installing metadata never enables background execution, remote trust, hosted
storage or source export by implication.

## Required mechanisms

### Domain and authorization

Use one logical PostgreSQL authority per domain, with `authority_id`,
`authority_incarnation` and `home_location`. In one database transaction validate
authenticated subject, tenant/project scope, Grant, Policy version, deadline,
resource claim and expected revision; apply the transition, append event and
Outbox, and persist dedup. Emit `accepted_by_authority` only after commit.
An idempotency key reused with different canonical input is a conflict.

Authenticated subject and tenant come from trusted transport/enrollment context.
Body fields cannot grant permissions. Separate send, invoke, source read/write,
publish and accept. Revocation, expiry, budget and policy changes must be checked
at the actual protected boundary, including dispatch and retry. Internal recovery
keeps the original command lineage and cannot expand its scope.

Scope, Root, Route, AgentSlot and WorkItem identity survive Machine, Node,
Runtime, Session, directory and transport changes. Keep versioned ScopeBinding
and HarnessSessionBinding distinct; retain retired binding provenance.

### Delivery and durable operations

Messages retain logical `message_id` through retries and Provider changes.
DeliveryAttempt records connection, selection revision, deadline and errors.
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
observations and never own Domain policy. Exercise real Codex and OpenCode
instances for conformance; native multi-agent collaboration must be disabled
for the relevant independence test.

MCP, CLI and versioned HTTP invoke one Domain service and schema. Validate actual
entry points, including unauthorized and duplicate commands. A2A is an optional
Gateway and ACP a Driver boundary, not alternative Domain authorities.

Directed CommunicationBinding resolves an authorized DeliveryPlan: addressing,
message, activation and receipt providers plus policy constraints. Candidate
selection uses observed capabilities and a bounded recovery budget. Human Bridge
requires exhaustion of eligible automatic recovery, a still-valid task and an
incident with attempted paths, evidence, expiry and recheck/exit conditions.
Successful re-probe returns to an automatic path. Late manual packets undergo
the same dedup, deadline, revocation and accepted-revision checks.

### Protected resources and acceptance

Lease binds owner Attempt, Runtime, Resource, mode, authority incarnation,
generation, fencing token, expiry and Grant. Test stale-owner rejection at the
real Effect/Resource gateway after replacement. Unfenceable resources stay
blocked until the old owner is isolated or confirmed stopped. Parallel Engineers
use separate worktrees/sandboxes; resource admission enforces deterministic
ordering, budgets, rate, concurrency and deadlines.

An external effect with an ambiguous result enters `uncertain`. Read back the
marker/result before adopting, compensating or authorizing a new Attempt. Partial
artifacts, stale baselines and unresolved protected effects cannot pass acceptance.

Execution evidence includes baseline, output commit/tree/diff/untracked manifest,
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
enrollment and data export are separate switches. Drain/checkpoint/export and
revoke old Grants before authority cutover; rollback exports new durable state
and retains audit facts.

## Validation and claims

`tools/bootstrap/audit_setup_baseline.py` records setup-only fresh-process evidence and
preservation inventory. Runtime Gate scenarios are defined in
[gate-contract.json](gate-contract.json). `tools/runtime/validate_gate.py` checks evidence
completeness and digests; a passing validator is not an independent runtime test
or authorization to accept/publish.

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

## External source reference

Codex App Server is an official structured integration surface for clients.
Driver implementation must bind observations to the installed version; the
documentation alone cannot establish deployment conformance.
[Official App Server documentation](https://learn.chatgpt.com/docs/app-server)
(retrieved 2026-09-11).

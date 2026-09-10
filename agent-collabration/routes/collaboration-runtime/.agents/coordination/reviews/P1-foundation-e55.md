# P1 foundation candidate review

Decision: changes requested. This review does not grant acceptance-ready,
Runtime support, or P1/P2 Gate passage.

## Frozen source and verification

- Candidate: `e55d9d7ef35e4ac626529652337be62a8676b398`
- Tree: `08f3b81aeb307da5ae7a0bfa6bfc2de129eec06c`
- Engineering branch: `codex/runtime-p1-engineering`
- Management contract: `0b2d55967d88aa552df7815b1e9febfb044041f0`
- Both clone contents and the published engineering branch were read back.
- Independent code review and Management verification were separate external
  Agent activities. Review source remained fixed during the probes.

The engineering suite ran 13 tests with the isolated PostgreSQL and Temporal
services enabled. Management retrieved the raw files and verified their digests.
Windows independently ran 10 tests; three service-dependent cases were explicitly
skipped. The existing setup suite ran 111 cases; Windows skipped five symlink
cases because that test process lacked the required privilege. The 35 offline
Gate-validator tests passed separately.

These tests cover a transaction foundation, SQLite journal persistence, injected
Driver adapters, a Temporal echo/query workflow and shared function/ASGI adapters.
They do not exercise a complete Domain-to-Node-to-Harness operation or actual
CLI/MCP transport conformance. The ASGI TestClient results are in-process tests.

## Management negative probes

Synthetic counterexample inputs were executed against the real, isolated
development services using the fixed candidate. These are observed invariant
failures, not successful product operations or accepted engineering evidence.

| Probe | Expected invariant | Actual observation |
|---|---|---|
| Expired command | Reject before mutation | WorkItem created; authority receipt returned. |
| Target outside Grant Scope | Reject before mutation | WorkItem created in another Scope under the same tenant. |
| Self-review plus `not_run` Evidence | Reject readiness | Same Engineer's pass Review advanced the WorkItem to acceptance_ready. |
| Domain/Lease integration | Validated Lease command or domain rejection | TypeError: required authorization permission argument missing. |
| Repeated completed Temporal operation | Read back the existing logical operation | Same operation ID produced two distinct Run IDs. |

Private probe result SHA-256 values:

- Domain/Lease probes: `c2b467be48f2502e050abbf5355fd8c68751c497490b0878a8f7ecea68d6349f`
- Temporal replay probe: `cdfff12b69cfe65b1e529cba7392cd3af1fc23574e0d5b790e6aa0c88dd0b054`

Raw test logs, probe scripts/results and operational details remain in private
evidence storage. They were read back independently from the engineering report.

## Required corrections

Line numbers below refer to the frozen candidate, not future revisions.

| ID | Priority | Source | Required behavior |
|---|---|---|---|
| E55-01 | P1 | `runtime/surfaces.py:79` | Verify actual transport/enrollment credentials. Identity and Grant labels supplied as headers cannot authenticate a caller. Protect reads as well as writes. |
| E55-02 | P1 | `runtime/domain.py:47` | Check command deadline, target Scope/AgentSlot, Grant scope, authority/incarnation and revocation together in the transaction. |
| E55-03 | P1 | `runtime/domain.py:151` | Validate Review target ownership and linked Evidence. Scope every Review/Evidence/Effect association to tenant/project/scope. |
| E55-04 | P1 | `runtime/domain.py:118` | Require an independently assigned Reviewer and complete, admissible, baseline-bound Evidence. Bind Review to the actual evidence set. |
| E55-05 | P1 | `runtime/domain.py:92` | Require separate acceptance permission; retain accepted_by, policy, parent, scope and authorized Finalizer lineage. |
| E55-06 | P1 | `runtime/domain.py:130` | Revalidate the sealed readiness state at final acceptance. Reject substituted references, revoked review, stale baseline and unresolved uncertain effects. |
| E55-07 | P1 | `runtime/domain.py:61` | Deduplicate command identity and idempotency identity consistently. A reused command ID must not create two operations while silently dropping an Outbox entry. |
| E55-08 | P1 | `runtime/temporal.py:119` | Explicitly enforce logical operation identity for completed and in-flight retries; recover the original handle/result and validate input lineage. |
| E55-09 | P1 | `runtime/lease_authority.py:31` | Connect the Lease store to the actual Domain interface and command transaction. Preserve monotonic generation and immutable identity on retry. |
| E55-10 | P1 | `runtime/lease_authority.py:55` | Recheck Grant, authority incarnation, owner, Scope/Policy and fencing at the resource boundary. Revocation must invalidate an otherwise unexpired Lease. |
| E55-11 | P2 | `runtime/surfaces.py:30` | Require explicit logical command/idempotency identity. Independent commands on one WorkItem must have distinct identities. |
| E55-12 | P2 | `runtime/temporal.py:157` | Complete worker shutdown and clear all connection/worker/task state after cancellation. |

## Remaining P1 mechanisms

After repairing the implemented Domain paths, connect the actual dispatcher,
Inbox/Outbox, durable Node mailbox/process lifecycle, Codex/OpenCode native
Drivers, protected resource effects/read-back and standalone MCP/CLI/HTTP
surfaces. Complete Source/Artifact provenance and binding continuity. Run the
full P1 restart/fault scenarios on a sealed integrated candidate before P2.

The Temporal test currently proves SDK workflow submission/query against a real
service. It does not prove Domain authorization, Provider restart recovery or
Outbox reconciliation. Driver wrappers currently use injected test endpoints.
EffectGateway currently returns a supplied reference after a fence check; it
does not perform an actual resource read-back.

## Environment observations

The engineering endpoint has Codex CLI 0.153.2 at its explicitly verified
installation path and OpenCode 1.18.30. Use the verified absolute executable paths
for repeatable probes. Driver lifecycle remains not_run.
Docker image digest and container instance ID are separate observations; use the
actual container ID for instance lifecycle evidence.

## Next action and synchronization

Management will issue a bounded repair command against this exact baseline.
Preserve the candidate for audit; return a new commit and regression evidence.
The receiver must fetch the review commit explicitly. Message delivery alone
does not update the receiver's checkout. P1 and both P2 execution Gates remain
not_run until their named contracts and complete evidence are satisfied.

# Runtime upgrade work and Gate route

This is a bootstrap coordination record for external Agents. Runtime domain
records will become authoritative only after explicit adoption and read-back.

## Goal and accepted architecture

Deliver the user-authorized Harness-agnostic Collaboration Runtime through P2.
The [adopted contract](../../../../../docs/runtime/UPGRADE-CONTRACT.md) identifies
the immutable input and precedence over earlier RFC examples.
Root: `agent-collaboration-root`; Route: `collaboration-runtime`.

## Work contracts

| WorkItem | Owner | Deliverable and acceptance |
|---|---|---|
| BOOTSTRAP | Management | Fresh source setup version/configuration/permissions, Root/Route validation and preservation inventory. |
| P1-CONTRACT | Management + independent Reviewer | Adopted delta, gate contract, negative evidence-validation tests. |
| P1-DOMAIN | Engineering | Actual PostgreSQL transactions, authorization, event/outbox/dedup, identity, revisions and acceptance guards. |
| P1-DURABILITY | Engineering | Real Temporal adapter/restart evidence; Node SQLite and process reconciliation. |
| P1-DRIVERS | Engineering | Codex/OpenCode lifecycle and actual MCP/CLI/HTTP parity. |
| P1-EFFECT | Engineering + independent Reviewer | Resource-entry fencing, uncertain read-back, stale/incomplete evidence rejection and finalization. |
| P1-INTEGRATE | Management + Reviewer | Sealed integrated candidate and complete named local Profile evidence. |
| P2-CODEX | Two Machine Nodes + external Codex Agents | Dual-machine/session collaboration and fault recovery after P1. |
| P2-OPENCODE | Codex + OpenCode Agents | Separate cross-Harness loop and recovery after P2-CODEX. |
| P2-REVIEW | Independent Reviewer + product owner | Exact Profile review, limitations, evidence expiry and owner decision. |

## Current scoped observations

Bootstrap source setup audit passed on Windows: 10 checks, 194 tracked files
preserved; the regression suite ran 111 tests with 5 conditional skips. This
proves the existing setup source/Profile only. Raw outputs, configuration
digests and inventory are retained in ignored private bootstrap evidence.
The nested configuration's source-repository-required flag was subsequently
aligned with its existing nested-repository manifest; validate that revision
again before consuming a future bootstrap record.

Initial Runtime Gate records are `not_run` under [gates/](gates/). No support
claim is inherited from the baseline, current native Harness relay, test fixture
or engineering self-report. Per-scenario evidence must replace the initial
record before a Gate can pass. Capability scope includes versions, direction,
credential/policy and expiry.

## Integration and authorization

Management owns this coordination surface and `docs/runtime/`; Engineering owns
Runtime code, tests and isolated development infrastructure. Use isolated
branches/worktrees. Freeze an implementation candidate before independent review;
test the actual integrated baseline before acceptance-ready. Runtime adoption,
protected publication and product acceptance are distinct operations.

The work policy permits scoped implementation, project dependencies, isolated
loopback test services and designated Harness tests. Existing unrelated services,
credentials and projects remain outside the resource grant. New high-risk access,
Hosted direction and final P2 owner review use the escalation contract from the
uploaded instruction. Save private transcripts and raw operational details in
ignored evidence storage; curate public source and Gate artifacts explicitly.

## Repository synchronization

Bootstrap implementation baseline: `a58c56c772d306cd5cef7cfca27deaf1ec240ebc`.
Both source clones were directly read back at that commit before dispatch.
The remote baseline was transferred by verified Git bundle after a stalled
GitHub fetch. This is explicit source synchronization; native message delivery
does not imply future fetch/pull. Every candidate handoff must report branch,
base/head/tree, working tree, commit/push result and receiver action.

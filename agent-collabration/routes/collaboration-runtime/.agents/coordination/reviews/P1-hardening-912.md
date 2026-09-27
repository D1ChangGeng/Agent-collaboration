# P1 hardening candidate review

Decision: changes requested. P1/P2 remain not_run.

## Frozen source

- Candidate: 912b19b4ae384baa8901ebc1182f950a04bec28b
- Tree: aed157df89a2018feea625c45bea61562345bc69
- Engineering branch: codex/runtime-p1-hardening
- Base: 7167d5948a7b6a7e8641410625f2e0932e25ecfd
- Push and both checkout identities were read back independently.
- Review date: 2026-09-11.

The isolated Runtime suite ran 19 cases and returned exit 0. Management read the
actual output and schema-version/checksum record. This establishes the recorded
test outcomes, not complete P1 conformance.

## Direct PostgreSQL counterexamples

Management executed synthetic counterexample inputs against the real isolated
development database, holding source at the candidate commit. No external Effect
was executed. The following guard outcomes were directly observed:

| Case | Observation |
|---|---|
| Management creates WorkItem; Engineer produces and reviews its own Evidence | acceptance_ready allowed |
| Independent reviewer approves minimal endpoint_reported Evidence with an invented digest and no execution bundle | acceptance_ready allowed |
| A different read-only principal presents a valid Lease tuple | fence helper allowed |
| A different authority incarnation presents the tuple | fence helper allowed |
| WorkItem has a verified Effect and another uncertain Effect; request lists only the verified one | accepted allowed |

Raw scripts/results remain in private review-912 evidence storage. The Effect
rows in the last case were explicitly seeded test fixtures; this proves the
Domain guard omission, not a real protected-resource operation.

## Repairs verified from code

Credential digest comparison replaced identity-label authentication. Common
create/transition paths now check deadline and several Grant/Scope associations.
Command/idempotency identity constraints, separate finalization permission,
readiness snapshots, reviewer assignment, and explicit Temporal replay policies
were added. Lease acquisition is connected to the Domain interface. These
changes are retained; the remaining defects below still prevent acceptance.

## Required corrections

Locations refer to the frozen candidate.

| ID | Priority | Location | Required result |
|---|---|---|---|
| R912-01 | P1 | runtime/domain.py:161; runtime/models.py:104 | A complete, immutable, baseline-bound Evidence Bundle must authorize readiness; summary labels and digest-shaped strings do not suffice. Recheck current evidence at acceptance. |
| R912-02 | P1 | runtime/domain.py:225; runtime/domain.py:164 | Separate review assignment permission from recording a review. Validate independence from actual implementation/evidence producers, not only WorkItem creator. |
| R912-03 | P1 | runtime/domain.py:175 | Validate the complete relevant protected Effect set. A caller cannot omit uncertain work from acceptance. |
| R912-04 | P1 | runtime/domain.py:163; runtime/domain.py:173 | Revalidate current reviewer authority/incarnation, assignment, Grant and Scope at readiness and acceptance. |
| R912-05 | P1 | runtime/lease_authority.py:86 | Fence against authenticated caller, current authority incarnation, Scope/Policy, permission and actual Attempt/Runtime owner. |
| R912-06 | P1 | runtime/domain.py:177 | Validate Effect-producer authority and Finalizer authority separately; permit a valid delegated production/finalization path. |
| R912-07 | P1 | runtime/domain.py:111; runtime/domain.py:217 | Seal causation in command identity. Assignments and Leases need the same command/revision/event/outbox/dedup contract; Evidence and Review must honor their revision preconditions. |
| R912-08 | P1 | runtime/schema.sql:31; runtime/domain.py:121 | Preserve legacy command_id from its recorded result and retain an explicit hash-version/replay policy. Never replace command identity with idempotency_key. |
| R912-09 | P2 | runtime/temporal.py:189 | Cancellation during close must leave a stopped worker or retained recoverable references, not an unreachable live worker. |

The independent reviewer also verified logic counterexamples using actual-method
AST extraction and memory fixtures. The migration example used the real UPDATE
against a SQLite memory fixture plus old/new hash comparison. Those observations
are source/logic evidence; they are not PostgreSQL migration or Temporal restart
proof.

Management subsequently reproduced R912-08 on real isolated PostgreSQL using
exact `e55d9d7ef35e4ac626529652337be62a8676b398` schema and a synthetic legacy
command row, followed by the exact candidate schema. Migration changed
`command_id` to the retained idempotency key while `result_json.command_id`
retained the different original command identity. The legacy payload hash was
unchanged. The probe ran in a new schema within an always-rollback transaction;
read-back confirmed that schema was absent afterward. This proves the migration
identity defect on PostgreSQL, not successful replay or complete data recovery.
Private raw evidence: `review-912/migration-identity-probe.json`.

The next repair must add real old-schema/data migration regression using
the preserved database checkpoint or an equivalent isolated legacy fixture.

## Required regression coverage

Test the five directly observed cases above, actual producer/reviewer/finalizer
separation, current-authority changes, causation and command-type conflicts,
revision races, command identity across all mutation types, and legacy retry
after migration. Successful acceptance needs real verified references in the
test profile; unavailable readers remain fail-closed. Test names must describe
the code paths actually exercised.

The next candidate must be sealed before final test records are attached. Keep
test-fixture claims distinct from full Source/Artifact/Effect and Harness E2E
evidence. Existing checkpoint/restore data remains preserved and isolated.

## Remaining P1 mechanism work

After the invariant repairs, implement the actual dispatcher and durable Inbox,
Node lifecycle and recovery, native Drivers, standalone MCP/CLI/HTTP entry
points, protected effects/read-back, Source/Artifact/Binding provenance and
integrated acceptance. The adopted Driver contract defines the next lifecycle
and protocol conformance scope. P3/P4 remain separate future Profiles.

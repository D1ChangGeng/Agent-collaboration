# Domain ledger and protected-effect component review

Decision: PASS for sealed component e93a4b6 and the measured Linux regression scope.
Full P1 and both P2 Gates remain not_run.

## Sealed source

- Commit: `e93a4b6b5115a2be7d45a4cd0c8b1ac3b2912bb8`.
- Tree: `023a3c8c142e509726e6ba30518eff9916a91029`.
- Parent: `9348c8a597e7b5435119b762d97ee679495545fa`.
- Scope: 17 source/test files for Domain, typed evidence, legacy migration,
  Lease authority and the Linux file Effect Gateway.

## Result and independent review

Current authorization precedes duplicate replay. Command and idempotency identities
are locked together; historical e55/912 records retain provenance and conflicting
claims are quarantined. Mutation, event, operation, outbox and dedup share a
PostgreSQL transaction. The authority binding comes from deployment context.

Execution receipts require an independently registered observer and Attempt.
Readiness and acceptance revalidate complete bundles, actual CAS bytes, reviewer
assignment and producer separation, Scope, policy and current authority. Readiness
freezes the candidate; subsequent authorized publication can add effects. Acceptance
requires the entire effect set and actual completion/readback proofs. Its final
write checks the evidence validity deadline against the database clock.

Lease mutations and expiry use consistent resource/row locks and current owner,
Grant, Runtime, Scope, incarnation and fencing checks. The Linux file gateway pins
directory identities, preserves immutable operation intent/completion history and
reconciles prepared writes before an explicitly authorized resume. Historical
readback checks current reader authority while retaining the original producer.
Acceptance reuses its PostgreSQL transaction for that readback.

Independent review found no remaining blocking defects in this component. The
sealed diff was compared to the reviewed source; final lint changes preserve
business semantics. Previously recorded migration checkpoint preservation and
Temporal/Artifact component evidence retain their separate scopes.

## Direct verification

Management exported the exact commit into a fresh source snapshot and created a
separate PostgreSQL test database. Linux 6.11.0-17, Python 3.12.3:

| Check | Actual result |
|---|---|
| Runtime regression, real PostgreSQL and Temporal enabled | 274 passed, zero skipped, 85.09 seconds |
| Offline Gate evidence validator | 51 passed |
| Existing setup regression | 111 passed |
| Ruff | PASS |

The real Domain/Lease/Gateway combination passes completed publication and rejects
a file written before its completion record is committed. The latter leaves
acceptance state and the four command journal counts unchanged. Tests also exercise
revocation, historical replay, lease fencing, contention and actual filesystem
recovery. Three intentional invalid-model serializer warnings and two dependency
deprecation warnings did not change outcomes.

Raw Runtime output SHA-256:
`293706cc3589d6b184c16075f6b219b947bc486997e9c83f14f9b9f7d237836b`.
Private report, JUnit and logs are retained in `review-e93/`.

## Remaining implementation and evidence boundaries

Node/Attempt admission and Effect registration are explicitly provisioned fixtures
in this component's integration tests. Formal authenticated registration interfaces
remain required. Gateway roots require exclusive service ownership, and the local
filesystem backend is Linux-specific. Function-level surface tests do not establish
standalone MCP/CLI/HTTP conformance. Temporal adapter recovery is measured; complete
Outbox dispatch, Node/process recovery, real Codex/OpenCode Drivers and the ordered
cross-machine/cross-Harness loops remain separate work and Gate evidence.

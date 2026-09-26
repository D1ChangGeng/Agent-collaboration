# Authenticated Effect registration and recovery review

Decision: PASS for sealed component `7f8c0f373aa73e4efaebfdc02d265b40b70bd8a8`.
Tree: `0dfdf54767098c35585d471ceb8565f5945a265d`.
Parent: `e93a4b6b5115a2be7d45a4cd0c8b1ac3b2912bb8`.
Full P1 and P2 remain not_run.

## Result

DomainAuthority now exposes `effect.register` and `effect.reconcile`, each with
current `effect.register` and `effect.read` authorization, complete command
identity, expected revision and the existing transactional event/outbox/dedup
contract. The service obtains candidate and Lease identity from locked Domain
rows and obtains intent, payload and completion facts from the actual file
Gateway. Requests cannot supply their own digest or completion proof.

Prepared writes register as uncertain. An explicit reconcile reobserves the
same intent and payload; it never starts a new write or Attempt. A replacement
publisher with current authorization can complete the original intent and then
reconcile while the retired publisher's Grant is revoked. Original registration
and producer provenance are retained separately from recovery command provenance.
Final acceptance reads actual completed output through the shared transaction.

Runtime schema 1.5 adds the registration/reconciliation proof fields. Formally
registered identity, including readback path, candidate, Lease, resource, original
operation, intent and payload binding, is immutable. Legacy rows retain their
existing provenance and the accepted WorkItem freeze continues to apply.

## Independent review and verification

The independent Reviewer found and closed two defects before this seal: recovery
was incorrectly restricted to the old Grant, and readback_ref was absent from
the immutable identity comparison. The sealed source and tests were read directly;
both fixes and the Domain/schema integration passed the scoped review.

A fresh exact-commit source snapshot with isolated PostgreSQL and real Temporal
returned **298 passed, zero skipped, 95.18 seconds**. This includes 24 new scenarios
for actual registration, duplicates/conflicts/revocation, prepared writes, original
owner recovery, revoked-owner replacement, acceptance and immutable-field rejection.
Ruff passed. Runtime raw output SHA-256:
`546ab37cd542163f4e8ef782b872ad2eff3365a1f965b1e3e0a4de0734ecf82e`.

A separate clone of the tested 1.4 database preserved 20 tables and 9 existing
rows through 1.5 adoption; repeating adoption was unchanged. A second probe
inserted six explicit synthetic legacy Effect rows, one for each prior status:
all old values survived, all 11 new proof columns remained NULL, and repeating
adoption was unchanged. Both migrated probe databases were then set read-only.
These are bounded migration probes, not large-dataset evidence.

Private raw logs and reports are retained under `review-7f8/`. Initial trusted
Node/Attempt enrollment remains a fixture in these tests. Actual Node/Driver,
standalone surfaces, dispatch recovery and cross-machine/Harness Gates remain
separate integration work. Existing Gate-validator and setup evidence remains
scoped to those unchanged source components.

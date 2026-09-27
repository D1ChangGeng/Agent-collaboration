# Signed Node enrollment and execution provenance review

Decision: PASS for component `3dcf94708832876084949720ca086a60e6d11307`.
Tree: `f7f6765bb1a7b4e1f5b42877205ef47a9f670e66`.
Parent: `f9bffec290e7804f930e794b7e30bccab87d853d`.
Full P1 and P2 Gates remain not_run.

## Result

Runtime schema 1.6 adds operator-authorized Node enrollment, rotation/revocation,
short-lived command challenges, and signed Runtime/Attempt registration. Private
keys remain at the Node. Public keys and signatures use PyNaCl 1.6.2/libsodium
strict validation; cryptography 50.0.1 signing interoperability is tested.

Current Node/key/Grant authorization precedes business dedup. Refreshing a proof
can recover an already committed command without replaying its business effects.
Proof audit is separate from business identity; original Attempt and receipt
proof references remain immutable. New execution receipts require current
bindings and are sealed at the actual database recording time. Previously stored
signed receipts retain historical eligibility across planned rotation and
future-only revocation, subject to existing Source, Grant, Scope, policy, CAS
and independent-review checks. No accepted revision is rewritten.

Runtime identity registration does not require an unrelated evidence-writing
permission. Reviewer and publisher roles retain their own permission sets;
evidence permissions remain enforced at the evidence action boundary. Registering
an observed start does not start a process or invoke a model.

## Review and verification

Independent review reproduced and closed weak-key authentication and proof-refresh
idempotency defects. Strict verification rejects the identity-key forgery and the
official mixed-order regression vector. Management inspected the actual Domain
hooks and exercised the integrated paths. Existing valid Node/Runtime/Attempt
fixtures now use real registration and signatures rather than SQL insertion.

A fresh exact-commit Linux snapshot, with real PostgreSQL, Temporal and configured
Docker, returned **390 passed, 8 Windows-only cases skipped, 135.37 seconds**.
This includes 33 new enrollment/crypto/source-identity cases and the existing
lease/evidence/effect recovery regressions. The archive runner supplies its verified
commit/tree explicitly, preventing accidental inheritance of a parent checkout's
HEAD. Ruff passed after import and newline normalization.

Actual Windows integrated crypto/source checks returned **7 passed, 26 Linux
PG/CAS cases skipped**. The complete Linux raw output SHA-256 is:
`8fbf94f49a7ccaa7d97dd57f97099689dab2aca31ec35e009fa683f587f6956d`.
Private outputs/JUnit are retained under `review-3dc/`.

A separate 1.5 test-database clone preserved 20 old tables and 9 rows, added seven
enrollment tables, and remained unchanged on repeated adoption. That clone was
set read-only. This is a bounded migration probe, not a production-size test.

These results establish authenticated registration and record provenance. They
do not establish actual Harness execution, network enrollment deployment, message
delivery, full sandbox conformance, or any P2 cross-machine/Harness loop.

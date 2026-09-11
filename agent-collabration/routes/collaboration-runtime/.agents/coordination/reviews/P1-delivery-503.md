# Durable Delivery 1.7 review

Decision: PASS for the PostgreSQL/SQLite/Temporal Delivery scope of
`503a9dfe2c0cc1012a97e82f36825efe1771aef5`.
Tree: `11badca5e8ef8044961be53ce0157261c2042c2b`.
Parent: `b63884e818037bc27e05718b95b86a74a750e24b`.
Management integration commit: `d5b192de815b83f69cc58cfeac988729726d2379`.
Native Driver composition, cross-machine transport and the P1/P2 Gates remain
not_run.

## Implementation

Delivery commits the logical message, original authenticated command, operation,
event, Outbox and `accepted_by_authority` receipt in one PostgreSQL transaction.
The packet binds WorkItem/Scope, receiving AgentSlot, source baseline, accepted
revision, deadline and bounded retry policy. The authoritative accepted-state
digest is derived from the committed Domain row; packet prose remains context.
Recovery cross-checks the independent command dedup, operation, event, Outbox and
authority receipt records before using the stored envelope.

Each DeliveryAttempt stores one immutable endpoint selection. Invoke activation
also stores immutable invocation, attempt, dispatch, receipt, envelope, logical
payload and accepted-state identities. PostgreSQL records `runtime_dispatched`
and activation location after side-effect-free Driver preparation and immediately
before the single native call. Failures before that marker are deterministic
rejections; missing results after it remain uncertain and are never blindly
reinvoked. PostgreSQL and Node SQLite keep monotonic receipt high-water state.

Node SQLite commits Inbox and invocation preparation under the journal/2 writer
fence. That fence orders Node boot replacement against the dispatch marker,
native call and observation. A replacement Core reuses the same un-dispatched
prepared attempt, including when the retry budget is one. Temporary endpoint
absence defers the message while retaining that open attempt; restoring the
endpoint executes it once. A marked attempt remains uncertain across replacement.
The schema adds a partial unique index for at most one open attempt and a bounded
attempt-state constraint.

Temporal runs the committed Delivery identity through an actual activity and
dispatcher. Activity cancellation waits for the underlying thread to settle.
Deterministic workflow ID/memo and run readback repair the window where Temporal
started but the PostgreSQL provider reference was not yet written.

## Independent review

The first independent review requested fourteen changes covering Inbox/selection,
dispatch state, authorization, accepted state, locking, attempts, invocation,
receipt ordering, Temporal cancellation/start recovery and ledger provenance.
After those changes it found three additional pre-dispatch recovery cases:
prepared invocation identity replacement, premature budget exhaustion and
temporary endpoint unavailability. All reproduced cases were fixed before the
seal.

The final Reviewer ran the focused Delivery, Node, Temporal, Domain-ledger and
legacy Temporal tests plus nine independent Grant/boot/prepared/dispatch
recovery cases: **117 passed in 76.22 seconds**. Ruff and diff-check passed.
Final reviewed hashes include:

- `runtime/delivery.py`: `4a2f0114b2359555b9ec5c8b036c87b294430a64938e888055ba4321fa988999`
- `runtime/delivery_models.py`: `4de6938e6fed5b0fcf5b02e681d1729855cc1bc66e9f317023277cf6b374708b`
- `runtime/delivery_node.py`: `dec0cbcdcf2562cdd375eb36f5c44a3d4a04b75c6c76177e0c564b51aa83857b`
- `runtime/delivery_temporal.py`: `9ee48f2aaf31f2a3a17da452f522eddda9d32e8c569ac6c3242eaf8e6d4be47e`
- `runtime/domain.py`: `ee1823bba057cb933c911ebb56ba6c2af3171d670da88ff8d0c7265b90893e8f`
- `runtime/schema.sql`: `a3eb11f7afdccfedab5e7f7c41c861f3b9d8f4853460cdd948b8fc77e23d8132`
- `runtime/temporal.py`: `66507f71c385e88952539330a4e11481363524423b03f2132945611b37eb284d`
- `runtime_tests/test_delivery.py`: `dfc0142b86d6d54325b16a3bab6b559667a70404c336a85fdae5bd47c157bca4`

## Migration and integrated verification

A real isolated schema was initialized from exact commit `3dcf947` as Runtime
schema 1.6, with one WorkItem and one row in each command/event/outbox/operation
ledger. Exact commit `503a9df` upgraded it to schema 1.7, preserving the WorkItem
and all four counts, adding the four Delivery tables and the one-open-attempt
index. Repeating initialization made no changes. Migration report SHA-256:
`d1bf31677ffe386a3ed213a0ff99f7c56ef8aa84d5833cd544b157c35c973b60`.

A fresh exact `git archive` of `503a9df`, bound to its commit/tree and run with
real isolated PostgreSQL, Temporal and the pinned local Docker image, completed
**553 passed, 8 Windows-only tests skipped in 184.91 seconds**. Private evidence
is retained under
`/home/changgeng/Agent-collaboration/.omo/review-912/delivery-503-full/`:

- pytest log SHA-256: `a3cd432e5195760ea399c2bb469adcabccf473feb0cb960ede037ae3051634f4`
- JUnit SHA-256: `abd954d7ce510d48d773cf0428a7f741f0a49e97eb9aa7177446a2b12fc36995`

Windows independently ran the SQLite/Temporal lifecycle subset: 13 passed, and
Ruff passed. Both work branches were pushed and read back from GitHub at their
exact commits.

This component PASS does not claim an authenticated remote Node transport,
native Codex/OpenCode adapter execution through Delivery, delayed asynchronous
response projection, Human Bridge recovery, real model work or cross-machine
completion. Those remain required by the P1/P2 Gate sequence.

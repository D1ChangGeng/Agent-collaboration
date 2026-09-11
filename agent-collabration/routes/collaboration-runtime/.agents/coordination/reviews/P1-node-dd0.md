# Durable Node observation journal review

Decision: PASS for sealed component `dd0e27dd603632575202ddaa753b4764d572408d`.
Tree: `09406c515d28d854ba69939ba8ec346684e27eea`.
Parent: `7f8c0f373aa73e4efaebfdc02d265b40b70bd8a8`.
This is Node observation/recovery evidence. Full P1/P2 remains not_run.

## Mechanism

SQLite persists machine/node identity, boot history, operation and mailbox
identity, receipt layers and process/spawn observations. Old boot instances cannot
mutate the journal or reactivate themselves after replacement. On restart, an
unfinished intent, dispatched spawn or still-running observation becomes uncertain.
Only the successful atomic `mark_spawn_dispatched` result permits dispatch;
completed or uncertain operations cannot silently start a second process.

The journal checks actual canonical payload digests and uses distinct bytes/JSON
encodings. Enqueue inherits previously observed receipt progress. Exact receipt
replay precedes ordering checks and cannot roll back progress. Missing layers remain
unobserved. Process observations require a consistent label, PID and start identity;
they are not OS containment or Harness conformance evidence.

Transactions retry lock acquisition before yielding, never repeat a transaction
body after it has executed, and close their connections on all exits. The original
five-column journal adopts new metadata while preserving stored digest bytes.

## Independent review and direct verification

Independent review reproduced and closed two bugs before this seal: a late mailbox
could remain pending after a terminal receipt, and a bytes payload could collide
with a JSON object. The final source and negative cases passed independent review.

Management ran a fresh exact-commit Linux snapshot with PostgreSQL and Temporal:
**347 passed, zero skipped, 95.13 seconds**. New Node coverage includes 49 SQLite,
fresh-process, conflict, migration, lock/connection and dispatch recovery tests.
The existing Node/Driver regression subset also passed. On the actual integrated
Windows checkout, the new and existing subset returned **55 passed in 5.18 seconds**.
Ruff passed for the new source and tests.

Linux full-suite raw SHA-256:
`4a7d4047654467e31cb79eacf30b8af36796cbbf60065bbdc2228b34fcdd3e69`.
Private Linux/Windows outputs and JUnit are retained under `review-dd0/`.

The source contains no Domain writer, model planner or automatic replacement
controller. Formal Node enrollment, Driver adapter integration, OS supervision,
message dispatch/recovery and actual Harness loops require their own evidence.

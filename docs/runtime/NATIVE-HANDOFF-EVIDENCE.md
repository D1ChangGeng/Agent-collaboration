# Native input handoff evidence

The optional `NativeDeliveryAdapter(..., record_handoff=True)` records receiving
evidence inside the existing Driver operation. The default is false. This is an
operator-injected library option; the receiver-factory configuration and generic
Adapter wire integration are separate work in WP03.

## Durable boundary

`NativeHandoffContext` contains the original Native operation/command/message,
stable ACS message reference, receiver address, Authority incarnation, receiving
epoch, provider generation, native Session, exact envelope/input/selection hashes
and authorization lineage reference. It contains no message body or credentials.

Both Codex and OpenCode bind this context into their existing invoke payload.
`DriverJournal.begin` commits that canonical payload in the same SQLite
transaction as the existing operation identity and Native fence, before the
function that can perform Native I/O runs. The existing Domain dispatch marker
and final authorization callback remain required. No new operation or message
authority, PostgreSQL table, or journal table is introduced.

Reusing a Native operation with a different context is an identity conflict.
Enabling recording preserves the exact payload of already-existing legacy
operations. A record already containing context continues to validate that
context if recording is later disabled. Context is not added to the prompt sent
to the native agent.

`auth_revision` is a digest referencing the admitted authorization lineage. It
does not grant permission to execute or replay; current Node and Domain checks
still determine admission.

## Query the original operation

`NativeDeliveryAdapter.reconcile_input(invocation)` authorizes observation and
queries the same Driver operation under the original binding. It does not invoke,
prepare, resume or retry input, and it does not submit an ACS reply.

| Observation | Result |
|---|---|
| Exact Native input readback, or an already persisted positive Native ACK, with matching lineage | `accepted`, with the actual native reference and journal evidence |
| Persisted pre-call rejection/deferral with no mutating I/O evidence | `definitively_not_admitted`, with journal evidence |
| Missing operation, inconclusive Native query or unavailable/corrupt journal | `unknown`, with `effect_possible=true` |
| Changed receiving generation for an unresolved input, or conflicting mutation evidence | `unknown`; no new input |

A positive ACK retains its original receiving epoch/generation after a Session
change. A replacement Session cannot erase that historical fact or acquire
permission to replay its input. Missing current Native history does not erase an
already persisted positive ACK.

Legacy operations can retain actual positive Native evidence while their
historical receiving epoch remains unrecorded. Their result uses epoch 0,
provider generation null and `legacy_receiving_epoch_unrecorded`; it does not
attribute the old operation to a current receiving selection.

Unknown input is never permission to retry. Ordinary delivery, native admission,
native consumption, explicit peer replies and business completion retain their
independent meanings. A new Session cannot resolve an old unknown input by
reusing an operation ID.

## Contract and verification

The internal handoff record is included in the generated
`receiver-evidence.schema.json` and TypeScript evidence DTOs. It is not an
additional public Native input endpoint. Signed receiver transport still
verifies the original admitted envelope through its existing authority.

`runtime_tests/test_native_handoff.py` exercises the real Driver implementations,
real SQLite commits and synthetic Codex JSON-RPC/OpenCode HTTP peers. Tests cover
the pre-dispatch persistence boundary, lost ACK, failure to persist a successful
Native ACK, repeat reconciliation, changed generation, canonical-input conflict,
definite refusal, legacy recording changes, corrupt context and contradictory
mutation evidence. Model reasoning and production-host qualification are not
measured by these peers.

The regression also exercises the existing real PostgreSQL atomic send/reply/key
paths and actual MCP process disconnect/restart tests in an isolated database.
Raw results and the exact source manifest belong to the development evidence;
production adoption remains separate.

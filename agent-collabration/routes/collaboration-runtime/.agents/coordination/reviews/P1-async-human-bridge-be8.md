# Runtime 1.9 asynchronous response and Human Bridge review

Decision: PASS for the frozen Runtime 1.9 integration committed at
`be8d06f002a720eeb28a4e50bf98f44edc53d76c`.
This is an implementation/component decision. Actual Codex model execution,
actual human manual action and the P1/P2 Gate decisions remain separate.

## Frozen identity

- base commit: `a942e6a292d2d2bebbaa8389a7deabe03798fac1`;
- base tree: `9d66cc338fa884de42f91b79a3114285232003f1`;
- corrected archive SHA-256:
  `75dff1645dfef629c26fecd22a3894f81eff341ce329afd84e629f3c98a8cd77`;
- manifest SHA-256:
  `cc1458c57be5f6a3242180a53566b9aa06e48dc3605052456ee7b1a5738d1c2a`;
- integration patch SHA-256:
  `e5ffe6b3f48831e081cccab96f00ed70178ced8a928eefef9c1701df970f96cd`;
- candidate tree: `1953a3d89af7541d481e248af9ac8ef624fd4e53`.

The first sealed archive carried the preceding commit's tree in metadata. It was
retained as superseded and was not integrated. The corrected archive, the local
staged index, all 38 LF targets and the candidate tree reproduce the identities
above.

## Asynchronous response projection

Native terminal responses are first committed to the Node SQLite response
Outbox. `NativeResponseCollector` calls only the Driver's read-only
`collect_result`; it never starts or resumes native work. Complete
message/command/operation/invocation/Attempt/dispatch/binding/session/turn
identity is checked before the observation is accepted. The first native
terminal timestamp is retained so exact collection and restart replay use a
stable canonical payload.

PostgreSQL locks the original message, Attempt and receipt lineage, performs a
final current-Grant/policy/revision/deadline check, then records one response
observation, receipt, audit and Outbox disposition. Retired, replaced, expired or
conflicting results remain fenced audit facts and cannot advance receipt
high-water. Response consumption has its own authenticated, idempotent single
consumer record.

Temporal retries only the pending projection/provider operation with the same
identity. Provider and Core restart cannot cause a second native invoke.

## Recovery commands and Human Bridge

Runtime schema moves from 1.8 to 1.9 only from the exact integrated 1.8 schema
SHA-256 `b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614`.
The migration is repeat-safe, preserves existing 1.8 rows and rejects another
predecessor before creating 1.9 state.

Projection/status/consume and incident open/request/reprobe/manual
receive/confirm/expire commands use the same authenticated Domain service and
MCP/CLI/HTTP Surface. A durable recovery command claim reserves command and
idempotency identity before action. Exact pending commands may finish the same
canonical action; changed concurrent commands conflict. Reserve, action and
finalize crash seams converge to one completed claim, one Domain result and one
audit/event lineage.

Human Bridge incidents require a complete exhausted automatic-path census and a
still-current task. A successful automatic reprobe fences later manual packets.
Manual packets do not carry authority: the Surface supplies authenticated
context and the normal Delivery receipt closes the incident.

The local file provider is POSIX-only. It uses owner-mode 0700 directories,
mode-0600 SQLite/files, descriptor identity checks, atomic publication and
durable notification/sidecar identity. SQLite runs in a bounded helper process;
timeout, EOF, malformed or partial IPC and broken pipes cause controlled cleanup
and bounded process reap. ACK loss and restart read back the same file/attempt
without publishing twice. Windows fails closed pending an equivalent ACL and
reparse-point provider.

## Actual and independent verification

The final Linux archive completed **939 passed, 25 skipped, 9 warnings in
326.98 seconds** with `PytestUnhandledThreadExceptionWarning` promoted to an
error. Ruff 0.16.6 passed. With the official PyPI index, `uv lock --check`
passed against the unchanged authoritative LF lock SHA-256
`f557ae56f153a87ba0bb48fe25ae5b4e4b0ee62f8555723d287f2b272ddfc4c5`.

An actual Windows OpenCode 1.18.27 `opencode/big-pickle` turn returned exactly
`ACS_P1_ASYNC_19_OK`. The trace records one `prompt_async`, one Node observation,
an injected first Domain-projection loss, Node/Core restart, and recovery by the
same Temporal workflow run. PostgreSQL contains one response receipt and one
consumption. The Job proof has no remaining or pending member. Evidence SHA-256:
`0ef766e628b7f39f451e647a1c6559f7aac53a8ff18e242d12ea9f922ff4b8bd`.

An event-subscription startup/claim-release race was reproduced during full
testing. The Driver now waits for subscription startup and stops/joins its event
thread before releasing the journal claim. Twenty claim-release rounds and 81
OpenCode/readback/adapter tests passed with unhandled-thread warnings treated as
errors; the actual model recovery was rerun after this fix.

Independent review repeated the fresh full suite as **939 passed, 25 skipped**,
plus 82 OpenCode/collector, 66 Human-provider/PostgreSQL, 47 formal
recovery/Surface/schema and eight additional concurrency/fencing cases. It
verified that eight simultaneous exact recovery commands create one incident,
audit and Domain event and that event threads stop before claim release.

Installed `acs-human-bridge` provision/snapshot ran in a minimal environment;
the provider root was mode 0700 and SQLite mode 0600. Test schema, helper,
Systemd unit, native process and tunnel residue were zero.

This result does not claim a Codex model turn, a real user forwarding/return
action, a Windows file provider, cross-machine delivery or any P1/P2 Gate pass.

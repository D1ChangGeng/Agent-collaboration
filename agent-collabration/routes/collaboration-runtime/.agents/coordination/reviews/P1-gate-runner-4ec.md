# P1/P2 Gate runner integration review

Decision: PASS for the evidence runner and P2 runbook component committed at
`4ecb36661198a2e88e510f839d440e1b79f20047`. This does not pass a Runtime
Gate: the measured P1 profile has one scenario with complete command evidence
and seventeen scenarios `not_run`; both ordered P2 Gates remain `not_run`.

## Frozen identity

- base `ac4d06a508860c5c56046b8b502d21a6fbccee36`, tree
  `91a4f5a4f96395920777d0b0cc04500abcd61544`;
- archive SHA-256
  `c9e9f3ef40d84eeae4cd341a968f5db8d10100654eacb4bbc7be982efc5c3df1`,
  mode 0444;
- manifest SHA-256
  `6ea3d95b1c61f86232faf433c2106639350801022524ce1fa10b5b2d8775902e`;
- patch SHA-256
  `ff8e4f2cc11aabf6180c9a8a1f09a33cc0484e737306978bd4a3abf4f9c2b128`;
- candidate tree `6202ee54523577a2f55adf826a4ac607d9d4d5ca`.

All 22 committed LF blobs match the frozen target hashes.

## Runner boundary

Probe execution uses the pinned, root-owned dedicated bubblewrap helper. The
probe sees an exact Git archive snapshot read-only and a separate writable
output root. Formal source, run state and the owner-only HMAC key are not mounted.
The runner records actual command stdout hash, source/Mode/Version/physical
Machine binding, receipts and readback references. A run state HMAC chain and
current HEAD/Machine readback reject tampering or a changed baseline on resume.
Windows lacks a reviewed equivalent OS sandbox and cannot run Gate probes.

The large formal checkout's tracked, untracked, sensitive ignored, Gate and
index inventory is kept in individually hashed canonical chunks. The HMAC state
contains the chunk manifest digest and counts. Initialization constructs a
complete private stage and atomically adopts it; failures cannot leave an
unreadable partial run. An actual checkout with 10,783 inventory entries and
four chunks produced a 5,862-byte state and passed init/audit.

The `host_loopback_providers` profile exposes only a validated mode-0600
owner-controlled profile and pinned Runtime environment at fixed sandbox paths.
The user bus is one UID/peer-checked Unix socket, never the host `/run` tree.
All source, profile, Runtime and bus ancestors are walked with no-follow
descriptors and pinned through subprocess launch. PostgreSQL and Temporal
connections are explicitly the host loopback addresses 127.0.0.1:54329 and
127.0.0.1:7239. Probe arguments and evidence omit DSN credentials and redact
userinfo for all URI schemes.

The P2 harness keeps stable Machine IDs in its template and observes current
Machine fingerprint, source commit/tree, versions and route at execution time.
It enforces P1, then P2-CODEX, then P2-OPENCODE. SSH reachability, two local
processes and stale inventory do not pass a cross-machine scenario.

## Independent verification

The independent Reviewer applied the exact patch and verified the candidate
tree, all 22 target bytes, Windows **90 passed/21 platform skips**, Linux with
available PG/Temporal **110 passed/1 skip**, Ruff 0.16.6, the locked dependency
check and diff-check. Ancestor links, swapped parents, wrong bus peer, changed
Runtime file inventory, profile digest and credential-bearing URI output were
rejected.

The Reviewer ran the frozen P1 profile in the pinned Linux sandbox. Its Domain
transaction scenario produced all six actual command-output, PostgreSQL,
SQLite, Temporal, Driver and OS evidence layers with one authenticated command
lineage and passed audit. The other seventeen scenarios stayed `not_run`; total
Gate status remained blocked. PostgreSQL test-schema residue was zero.

The P2 harness independently initialized and audited both eight-scenario Gates
as `not_run`, with source and Machine identities re-observed. No formal Gate
record was overwritten and no fixture-derived PASS was produced. Real Codex
model work and the ordered dual-machine/cross-Harness fault scenarios remain
required.

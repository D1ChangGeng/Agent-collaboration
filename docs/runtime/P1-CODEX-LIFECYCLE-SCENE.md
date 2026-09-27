# P1 Codex lifecycle scene

The P1 Codex scene binds one external command, delivery message, PostgreSQL
attempt, Temporal Workflow/Run, Node invocation, native turn, response artifact
and Systemd unit to the same Gate run. Runtime checks current Domain authority
at the protected boundaries. The external Agent supplies the fixed task packet;
Runtime does not choose the task or accept its result.

The runner pins an owner-0600 scene profile and an owner-0600 one-turn budget
decision. The decision ID is `P1-CODEX-LIFECYCLE-ONE-TURN-01`; its file also
binds the **actual running** source commit/tree and the scene-profile SHA-256.
It authorizes one `turn/start`, at most six native terminal collection reads,
120 seconds, a fixed tool-free prompt and no implicit retry. The monetary cap
is `unknown` until an external hard-limit observation exists. The provider key
is represented solely by an owner-0600 absolute path and path digest; the host
verifies its inode with `O_PATH` and never reads or copies its bytes.

The host owns a private `/run/user/<uid>/acs-p1-codex/<run-id>` directory. Its
`bin/codex` is a streamed, SHA/size-verified copy of the reviewed 0.153.2
native executable (mode 0500). The scene also pins an existing owner-0600
complete model catalog by path/SHA/size; the host validates the chosen model
and copies the catalog into its private Codex home. The catalog content stays
outside the candidate source and evidence package. The host holds private Codex config, Node/Driver
journals, artifacts, an endpoint socket, a run-specific Systemd EnvironmentFile
directory, and immutable readback. A host-owned `CodexHostNodeEndpoint` accepts
only fixed `dispatch` and `readback` requests. The sandbox receives read-only
scene, budget and readiness files plus that one socket at fixed paths. Systemd
and the user manager remain host-side.

Before dispatch, the guest records the WorkItem and `message.send` command in
the host-prepared PostgreSQL schema. The Host Node verifies the committed
command, run/Scope/AgentSlot/Authority identity, current Grant permissions,
Scope Policy digest, deadlines and pinned native/config digests. It records a
boot intent before Systemd launch and holds the PostgreSQL current-authority
lock through process birth and the final database-clock deadline check. The
host-owned Temporal worker submits `acs-delivery/<operation-id>` once. The
Node/Domain marker precedes one native turn. A dropped socket response is
reconciled only through `readback` of that original command and attempt.

The host collects the original terminal turn, writes a content-addressed
artifact, records the Node response Outbox and projects the same attempt to
PostgreSQL. Its Driver readback records the original terminal event hash and
the matching turn's token-usage notification when emitted; absence is recorded
explicitly. Any native server request blocks the tool-free scene. It stops
the run-labelled Systemd unit and retains unit, birth,
cgroup and EnvironmentFile evidence. Six Gate commands re-read command output,
PostgreSQL, Node SQLite, Temporal, Driver/artifact and OS evidence. Every layer
must carry the original command/message/attempt identity. The runner performs
an independent host-side postflight after command completion or interruption;
an unresolved boot intent or surviving unit remains `uncertain` and cannot
authorize another invoke.

The candidate's no-model evidence uses a Codex-shaped stdio fixture for the
complete same-run path and separately starts and terminates the reviewed real
Codex 0.153.2 binary with zero model turns. Actual provider output, usage and
cost observations require a new exact-commit budget decision and independent
review of this candidate. Until then, P1-CODEX-LIFECYCLE and the P1 Gate remain
`NOT_RUN`.

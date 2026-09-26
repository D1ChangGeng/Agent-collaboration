# P1 Gate runner isolation contract

Status: integrated isolated runner utility. P1 remains NOT_RUN until the real
Runtime mechanisms supply reviewed probe commands and complete evidence.

The source checkout is an immutable identity input. Probe commands execute only
inside a private per-scenario copy of an exact read-only HEAD snapshot. This
candidate never passes the formal checkout or Gate output path to commands and
never writes its Gate records into the formal `gates/` tree. A run directory
must be private evidence storage outside the checkout.

The runner owns orchestration, exact command capture, hashing, run recovery,
binding propagation, secret scanning, manifest generation and invocation of the
existing offline validator. PostgreSQL, SQLite, Temporal, Drivers and OS probes
remain authoritative only for the concrete facts they read back. A command exit
code or earlier component report cannot promote a scenario.

The P1 profile is one observed physical Machine and one enrolled Node. Codex and
OpenCode Harness/Driver versions are pinned in the binding. Multi-machine Gate
aggregation is outside this candidate; two processes or two labels on this host
cannot be submitted as distinct Machines.

All scenario output is fail closed. Before any scenario becomes passed, it must
contain the six evidence kinds and all seven evidence-reference groups required
by the Gate contract, concrete command/operation/message/event/receipt IDs,
affirmative fault injection and read-back facts, direct evidence state, bounded
timestamps and zero unresolved items. Exact replay resumes stored command
outputs only after their bytes, SHA, run ID, scenario, command, commit, tree and
binding digest are rechecked.

The source guard inventories full tracked and untracked content, ignored
sensitive paths, Git HEAD/tree/index/status, and protected `gates/` identities
before and after execution. A detected delta is recorded, marks the run
compromised and prevents finalization. Relative source-write, Gate replacement,
secret-file and Git index commands remain contained in the workspace, which has
no `.git` directory.

Large inventories are stored as bounded canonical chunks under
`source-guard/`. Their manifest binds every chunk digest and count, ordered path
range, classification digests, total bytes and the complete inventory digest.
The HMAC state stores only that manifest reference, digest and counts. Resume
reconstructs and verifies the complete inventory before comparing live source.
Initialization builds all evidence in a private sibling stage and publishes the
run with one atomic rename; failure removes the stage and leaves no adopted run.

Source hashing is defense in depth. A probe is admitted only through a verified
OS sandbox with the exact archive mounted read-only and a separate writable
output mount. The formal checkout, Gate tree, run root and state key remain
absent from the probe namespace. When no reviewed provider is available, the
scenario remains `not_run`; there is no subprocess-only fallback.

State authority belongs to the runner process. An owner-only random key signs a
revisioned HMAC chain, and the key is excluded from manifests and probe mounts.
Resume authenticates state before using any stored identity, then re-observes
Machine and Git source facts. A new clean commit requires a new run.

Plans may bind a reviewed local provider configuration with `runtime_profile`.
This mode is POSIX-only and fixes PostgreSQL and Temporal to the reviewed
loopback ports. The profile requires an owner `0700` parent and is an owner
`0600`, single-link regular file. The runtime environment is owner `0700`; its
owner `0600` manifest lists the exact path, mode and SHA-256 of every file.
The sandbox sees these inputs only at `/run/acs-p1/profile.json` and
`/run/acs-p1/runtime`. It verifies the owner user-bus socket and peer UID,
then mounts only that socket at `/run/user/<uid>/bus` for the OS readback.
Probe arguments, environment and output contain no host path or credential.
Plans without this field receive no runtime mounts.

`tools/runtime/gate_runtime_provision.py` copies an already reviewed Python
dependency directory plus the tracked P1 probe into a private sibling stage,
writes the complete environment manifest, performs the same runner validation,
and atomically publishes the destination. A postflight failure removes the
published destination, so it cannot be adopted by a later plan. The frozen
`p1_profile_plan` generates the Domain transaction command set; provisioning
attaches the exact runtime profile without changing the 18-scenario order.
Only `P1-DOMAIN-TRANSACTION` has a real lineage adapter. The other 17 remain
`NOT_RUN` until independently implemented and reviewed.

Potential secret material is rejected before successful stdout is persisted.
Only a redacted failure artifact and a redaction event may remain. The final
audit scans all run files again.

Synthetic tests exercise rejection and `not_run` behavior only. They are not
P1 evidence and must never be copied into a real run.

# Authenticated receiver Runtime 1.8 integration review

Decision: PASS for the frozen Receiver integration committed at
`bdbddf16b9eee7e7be19bd2a396e8f292b5ba45e`. This establishes the reviewed
same-host POSIX Receiver profile. Real model delivery and the P1/P2 Gates remain
separate.

## Frozen identity

- base: `a97d854ab0d602dad77b9a9c8690022239028113`;
- base tree: `a5fa91c0edb878ffd0b7a3e2477e59d313efd0db`;
- archive SHA-256: `2032dd3152e41926280a4c5e17e1c61fc6df4392ce7ae17aeb3cfc5635733031`;
- manifest SHA-256: `8733adf5f6d8ae80f3b7cedb9f9f5ea611dfecda8509cec0f30a2d73aea2c656`;
- integration patch SHA-256:
  `a670b6b3b0e98a566df86ce251e9be65232115ef3c4e212a6580042e15dce457`;
- provisioned wheel SHA-256:
  `2d69407e7d20ec3799ed133cf9b4227a6dfad102acacac364be111e32514a14c`.

All 31 committed target blobs match the frozen LF manifest.

## Integrated behavior

Runtime schema 1.8 adds authority transport keys, deployment connection
references, endpoint registrations, signed transport admissions and signed
receiver receipts. The migration accepts only the exact 1.7 predecessor,
preserves existing rows and is repeat-safe. Setup and Workspace schemas remain
independent.

Enrollment adds signed endpoint and Delivery challenge purposes. Endpoint
registration consumes the current Node challenge, Grant and Runtime identity.
The Domain stores current and historical authority keys, configured connection
references, complete canonical registrations/admissions/receipts, signatures,
digests, command lineage, events and Outbox state.

The remote endpoint is built only from a committed registration and configured
connection reference. Delivery orders signed prepare, prepared-receipt storage,
the existing PostgreSQL `runtime_dispatched` marker, then signed dispatch.
Readback cannot invoke again. The Receiver journal preserves complete request
identity, uses one durable logical dispatch marker, and holds its boot writer
fence through final authorization and native scheduling. Exact concurrent replay
does not replace the active owner; crashed or expired ownership becomes
uncertain without reinvocation.

The Receiver is POSIX-only. Private directories are owner mode 0700 and key,
journal and configuration files are mode 0600 with no-follow descriptor and
identity checks. Windows constructors fail closed.

## Installed entrypoint

The wheel includes the Runtime, reference deployment package, Receiver verifier,
provisioner and console entrypoints. The reviewed provisioner verifies wheel and
RECORD contents, stages under an owner-private directory, writes a complete
installation manifest, fixes directory/file/launcher modes, fsyncs, atomically
adopts the target and runs postflight. Failed postflight leaves no adoptable
target.

The final self-provision test first installed the same wheel into a bootstrap
environment, then invoked that installed `acs-receiver-provision` under
`umask 0002`, an empty environment and no `PYTHONPATH`. `--ignore-installed`
made the stage independent of the already-installed distribution. Two fresh
targets succeeded; an existing target was rejected without changing its
manifest. Each target contained nine mode-0700 directories, 63 files, mode-0600
ordinary files and two mode-0700 launchers. All 61 RECORD entries, both
launchers, the installation manifest, current interpreter path and interpreter
binary were read back.

The installed `acs-receiver` then ran under `SystemdUserSupervisor`, performed
its TLS 1.3 presented-certificate self-probe and handled signed prepare,
dispatch and readback. Unit/InvocationID/cgroup and policy were read back;
termination proved inactive state, an empty cgroup and wrapper exit.

## Review and verification

Four independent review cycles found and closed: incomplete transport identity,
duplicate logical dispatch, mutable claim ownership, missing final boot/current
checks, incomplete historical signed records, TLS readiness gaps, generation
restart, private-path/SQLite identity, concurrent replay, missing actual console
execution, unbound deployment configuration/factory identity, incomplete wheel
verification and a self-provision same-version no-op.

The final independent Reviewer applied the exact patch and ran:

- focused Receiver suite: **129 passed**;
- full Runtime suite: **829 passed, 21 skipped in 285.83 seconds**;
- Ruff 0.16.6, uv 0.8.9 lock check and `git diff --check`: PASS;
- real PostgreSQL, Temporal, TLS and Systemd lifecycle: PASS;
- PostgreSQL test-schema and Systemd unit residue: zero.

Wheel missing/changed/unrecorded code, altered RECORD, launcher, interpreter,
mode and postflight failures were all rejected. The Receiver model invocation
was deliberately disabled in this component run. Cross-machine routing,
asynchronous response projection, Human Bridge integration and P1/P2 Gate
acceptance still require their later integrated evidence.

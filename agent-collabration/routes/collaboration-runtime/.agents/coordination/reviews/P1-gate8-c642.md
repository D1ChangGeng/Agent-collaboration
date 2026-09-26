# P1 exact-baseline eight-scenario Gate review

Decision: `PASS_BOUNDED` for eight P1 scenarios on formal working-branch
commit `c6424f5b17a881e5fe6c0183a83641fd59aa88c7`, tree
`92d01d5c4de9e6a76b7a5bb76a1a2d4583e0860c`. The overall P1 Gate remains
`blocked`: eight of 18 scenarios passed and ten were `NOT_RUN`. The Route's
formal P1 Gate record was not changed.

The owner-only run ID is `p1-run-a5631eed31a24ddaa3b90eede7102169`.
The plan SHA-256 is
`8ce3194bd547294e7cb5a70a8c33a6ddb8bf7587a7ad6053d33648b9335ca8a8`;
the state SHA-256 is
`591d5bb9186a4669ca932fe8b4f5cfca708b103d6b28b6e11a6b97a2f7ce06ae`;
the run-manifest SHA-256 is
`ed3cdf0483565e550d7cadf77c7c1808951d5e890044b97e64d9a69a7c4b9d86`.
The run used an owner-only profile, host-loopback PostgreSQL and Temporal,
and a reviewed read-only Python runtime environment. The tracked source
checkout was clean before and after the run.

The passed scenarios were Domain transaction, auth revocation, command dedup,
Inbox ACK loss, Core restart, Node restart, Provider restart, and Lease
fencing. Each scenario produced six distinct command-output, PostgreSQL,
SQLite, Temporal, Driver and OS evidence commands: 48 of 48 passed. Provider
restart used its actual Delivery Temporal Workflow; the other seven used
auxiliary Temporal markers with the same scenario identity, and do not claim
that Temporal invoked their Delivery dispatcher.

The independent reviewer loaded the state through its HMAC verifier and checked
all 112 run-manifest files for SHA, owner-only mode and symlink exclusion. All
48 raw outputs matched the run, source, Machine, binding and command lineage.
Eight host OS attestations, Node SQLite boot/journal/mailbox/receipt records,
live PostgreSQL authority rows and eight completed Temporal Workflow/run pairs
agreed. The Reviewer confirmed exactly eight run-owned probe schemas and no
extra P1 probe schema. For Lease fencing, the second owner's independent
generation-2 file readback preceded the first owner's rejected late write;
pre/post file inode, marker and PostgreSQL row digests matched. The current
effect content and inode matched 11 owner-only markers. Raw outputs contained
no profile password, DSN or secret hit. No matching probe process remained.
The owner-only independent review JSON SHA-256 is
`64d06d1d57d219ea2846e99d7e759fc9f1bf3d52479d02e7564166bd24751512`.

After independent live review, a digest-bound cleanup dropped only the eight
schemas listed by this run's ledgers and confirmed zero P1 probe schemas.
The state and manifest SHA-256 values stayed unchanged. Its owner-only cleanup
report SHA-256 is
`3eb3e8b28416f079db911f3ac672422178006a9e489feb67390b72e6ca5f7dd9`.

Harness replacement, uncertain effect, stale baseline, partial artifact,
surface parity, Codex lifecycle, OpenCode lifecycle, native multiagent-off,
identity continuity and integrated acceptance remain `NOT_RUN` on this
baseline. A later source commit requires a new exact-baseline Gate run before
its own scenario claims can be promoted. P2 requires completed P1 acceptance.

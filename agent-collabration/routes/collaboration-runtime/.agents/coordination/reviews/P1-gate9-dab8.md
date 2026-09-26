# P1 exact-baseline nine-scenario Gate review

Decision: `PASS_BOUNDED` for nine P1 scenarios on formal working-branch
commit `dab8e9670357aba8786451a6a6f52f6727dde72d`, tree
`bf2c4bad3389d6d97538680898afc43f179ff93b`. Nine of 18 scenarios
passed, nine remain `NOT_RUN`, and the overall Gate is `blocked`. The Route's
formal P1 Gate record was not changed.

The owner-only run ID is `p1-run-bec67cf68c70c52ac3cd64b6e2e31be1`.
The plan SHA-256 is
`eee6ea5447f202af53ca7f8e9091332bff90acf708b1c7592886ec7bfdc04e35`;
state SHA-256 is
`b93830c5b853bebe3ac4c12c85a77ea3bc6f86bbcaaeff7b718be82bdfc81ec9`;
run-manifest SHA-256 is
`d0b939ab8432b906300d3c025b5f72b47872a17c8b185176cb1a742f8460cf04`.
The tracked source checkout stayed clean. Before this run, the same integrated
source passed the full Linux Runtime and P1 probe test selection with exit 0;
its owner-only test log SHA-256 is
`61fa0c5ea826667bc5d71eb015637cd35c208db19bca7de268c7968ba0319010`.
The postflight reported zero non-system PostgreSQL schemas.

The passing scenarios were Domain transaction, auth revocation, command dedup,
Inbox ACK loss, Core restart, Node restart, Provider restart, Lease fencing,
and Uncertain Effect. Each produced six distinct command-output, PostgreSQL,
SQLite, Temporal, Driver and OS commands: 54 of 54 passed. Provider restart
used its actual Delivery Temporal Workflow; the other eight Temporal runs are
auxiliary markers of the scenario identity, not claims that Temporal invoked
their Delivery or Effect mechanism.

An independent reviewer loaded state through the HMAC verifier and checked
all 134 run-manifest files, source snapshot, source guard, plan and profile
digests. All 54 raw outputs agreed on run, source, tree, Machine, Node,
command, operation, message, event and receipt lineage. Nine owner-only host
OS attestations and the physical Machine fingerprint agreed; live PostgreSQL,
Node SQLite and nine completed Temporal Workflow/run pairs were read back.
Auth revocation retained zero attempts and zero Node mailbox entries.

Lease review confirmed two released generations, the new owner's independent
readback before the first owner's late rejected write, and unchanged file,
inode, marker and PG snapshots across that rejection. Uncertain Effect review
confirmed `uncertain/prepared` after an external write and lost completion
marker, acceptance rejection without a successful command-dedup record,
same-operation reconciliation to `verified/completed`, one target write,
matching CAS bytes and Effect marker, and old-owner fencing. These checks do
not imply final WorkItem acceptance: the observed AcceptedState was a readiness
revision. Raw outputs had no DSN, password or common key-pattern hit. The
owner-only independent report passed 60 of 60 checks; SHA-256:
`361b832d26f04bfbd6885e373ea87795e56815cfbe02d10ae4016526343595c8`.

After that review, digest-bound cleanup dropped only the nine schemas listed
by this run's ledgers and confirmed zero residual P1 probe schemas. State and
manifest hashes stayed unchanged. The owner-only cleanup report SHA-256 is
`11431bac8cc302cab4a2c0233c9a14c99184753094fdc5335581d6eefb7b8ea6`.

Harness replacement, stale baseline, partial artifact, surface parity, Codex
and OpenCode lifecycle, native multiagent-off, identity continuity and
integrated acceptance remain `NOT_RUN` on this baseline. A separate Source
admission investigation reproduced same-size tracked-secret edits that Git
status missed; its product fix requires independent review. Later source
commits require fresh exact-baseline Gate evidence before their scenario
claims can be promoted. P2 remains gated on complete P1 acceptance.

# P1 Codex host Node entry review

Decision: PASS for the bounded host Node entry from exact base
`9717b7c41b09c637c1ee43f444614be7b62bb480`. The four source targets
stage to tree `1aa4363a5a218d37af492dc378e55cf62e740793`. This decision
does not enable `P1-CODEX-LIFECYCLE` or change the formal Gate.

The frozen r2 archive SHA-256 is
`46c2a8b409721187cf33de68e7afd62a6414a347b7f5aefcbcc32127828bf33f`,
manifest SHA-256 is
`854141d2f23fb862bfc438aebc5c854c9f2789864ad437361d65d7ee47cfe97e`,
and patch SHA-256 is
`9d979b8fe66a6f9d01ee9da0706a712097786bb9f11acc8333b509984c127887`.
The executable no-model fixture is Git mode `100755`; all four LF blob hashes
and modes match the frozen candidate. The staged tree was independently
reproduced on Linux and in the formal checkout.

The socket offered to a sandbox guest accepts only fixed `dispatch` and
`readback` requests. The host owns PostgreSQL authorization, the Node SQLite
journal, the Delivery dispatcher, the native Driver and Systemd supervision.
The guest supplies no executable path, argv, environment, PID, unit name or
user-bus access. The host checks the already committed message, source,
attempt, deadline and current Grant before protected work.

The first candidate was rejected because a post-send Grant downgrade still
allowed a host process to start. In r2, `start_native` rechecks current
`message.send` and `runtime.invoke` permissions, Scope, Authority, AgentSlot
and policy under a PostgreSQL transaction through the Systemd birth check.
The independent reviewer repeated the original real-PG downgrade case: the
start was refused, with zero new spawn, delivery attempt, Node receipt, boot
intent and matching Systemd unit. Scope, Authority, Slot and policy changes,
concurrent revocation, expiry cleanup and normal no-model paths were also
exercised. Independent Linux results were 21 passed and one platform skip;
Windows reported one passed and 21 platform skips. Ruff passed. Temporary PG
schemas, test units and EnvironmentFiles were cleared.

The proof remains a local no-model component result. Actual Codex binary and
provider, Temporal dispatch, terminal response projection, external budget
decision, host-crash postflight and model invocation are `NOT_RUN`. The
versioned HarnessSessionBinding and formal P1 Gate also remain separate
acceptance work.

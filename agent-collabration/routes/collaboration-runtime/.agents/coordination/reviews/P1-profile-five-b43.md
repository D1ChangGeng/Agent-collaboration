# P1 Profile first five scenarios

Decision: PASS for the frozen P1 Profile harness component committed at
`b43eed6e1041cdddb992ca86efcbc485301fdf0b`. This is not a P1 Gate pass:
five scenarios have a runnable real lineage and thirteen remain `not_run`.

The cumulative candidate is based on
`0e75c502b93166081aec30610c94df62e88bbd05`, tree
`8011018a41489299722014bfd75911aab61905ef`.
The first-group archive SHA-256 is
`dc8036eaab1c2f3c1b9da6c19df717c26f93f650515dea57ada664d1f1bd4759`.
The cumulative Core-restart archive SHA-256 is
`68d19eacf9760e4e7b592242d557e5778ff2115a7cfaee4e1607d53e390e80e1`,
with patch SHA-256
`c85602c85583edcedab0065e4736d191ed37054561c04385646db73f685fe10b`.
All four final Git blobs match the reviewed LF hashes and sizes.

The Domain transaction scenario binds one authenticated command, message,
operation, event and receipt across real PostgreSQL, Node SQLite, Temporal,
Driver and OS readback. Three additional scenarios were executed with the same
fixed-lineage discipline:

- **Auth revocation:** a queued send loses its Grant before dispatch; Domain
  blocks it and PostgreSQL/Node/Driver readback shows zero Attempt, Inbox and
  native call.
- **Command dedup:** exact replay returns the existing result; changed canonical
  payload conflicts; operation, event, Outbox, Inbox and Driver call each remain
  single.
- **Inbox ACK loss:** Node commits the Inbox and the first ACK is lost; the
  second DeliveryAttempt reads back the same message and Driver runs once.

Independent review repeated Linux unit, real PostgreSQL/Temporal and Gate
regression tests. Its own three-scenario × six-layer readback produced 18 passes,
all correlated to the same run/source/binding/message/operation/event/receipt.
Tampered Grant, command canonical hash and first Attempt state were rejected.
The first group has output directories mode 0700, evidence files mode 0600,
zero credential output hits and zero schemas created by that review remaining.

The cumulative candidate adds **Core restart**. A separate Core process exits
with code 83 after PostgreSQL commits a prepared Attempt but before Node/Driver
contact. A replacement Core recovers the same prepared identity and makes one
native call; post-dispatch crash replay does not call it again. Independent
review ran Linux **54 passed, one Windows-only skip**, the two Core restart
cases, and its own six-layer readback. Context and Attempt-state tampering were
rejected, with one Inbox/Node Inbox/Driver call and no schema residue from the
review.

The profile catalog still lists all eighteen contractual scenarios. At this
commit, five are implemented in the harness and thirteen have empty plans.
Actual Codex model execution, integrated acceptance and both P2 Gates remain
outside this component result.

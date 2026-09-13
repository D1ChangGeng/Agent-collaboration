# P1 identity continuity evidence boundary

The logical identity is one tenant, authority incarnation, WorkItem, Scope,
AgentSlot, Message, command, operation, Machine, Node and source commit/tree.
A Core, Node, receiver or Provider replacement may change a process PID,
Node boot, endpoint revision or runtime revision only through a signed current
registration. It cannot replace the logical identity or create another Inbox
projection or native dispatch.

`tools/runtime/p1_identity_continuity_probe.py` currently verifies genuine
authority request signatures, Node endpoint registration signatures and
receiver receipt signatures. It compares every admission and receipt field to
the same committed Attempt and rejects changed Machine, Node, Scope,
AgentSlot, authority incarnation, source commit/tree, body digest, boot or
registration. Exact signed request/receipt replay is idempotent; a conflicting
receipt under the same request ID is rejected. The no-PG component tests use
a real ReceiverService prepare/dispatch, signing keys and SQLite ledger.
A second no-PG regression reclaims generation 2 under a signed new boot and
recovers the **same** prepared Attempt once; exact replay does not invoke the
native fixture twice. A separate-process TLS 1.3 test runs signed
prepare/dispatch/readback through the real RemoteNodeTransport, checks one
receiver-ledger native call and terminates the service process. The
component reader reopens that ledger through its owner-path witness and checks
request, boot/generation and native-dispatch IDs against the same Attempt.
These remain receiver component observations because no single
Domain/Temporal/Core/Node process run produced those facts together.

This component returns `gate_status=not_run`. It does not create a Domain
WorkItem, perform a process restart or collect a P1 Gate result. A Gate adapter
may be enabled only after one private run proves all of these on the **same**
Message and WorkItem:

- PostgreSQL: authenticated WorkItem, accepted revision, Scope/AgentSlot,
  signed Node/Runtime/endpoint registration history, every DeliveryAttempt,
  committed operations/events/Outbox, receiver admissions/receipts and exactly
  one Inbox projection. Old boot and abnormal rebindings must remain fenced.
- Node SQLite: the same command/message/operation, boot history, mailbox,
  signed receiver request/receipt history and one actual native dispatch or
  an explicit no-model count.
- Temporal: a recorded workflow and run ID for the same operation, with a
  Worker restart and readback of its result.
- Driver and OS: one dispatch bound to the original invocation, real Core and
  receiver process exits/replacements, TLS certificate readback, user service
  and cgroup cleanup.
- A deliberately lost transport ACK, a Core restart, a new signed Node boot
  and a Provider restart must be observed in that one run, with the next
  authenticated receipt preserving the original logical identity.

A separate receiver test and separate Core/Node/Provider restart tests are
component evidence. They cannot be combined into a P1 Gate pass. Distinct
Machine transport evidence, actual model behavior and full acceptance are
outside this component.

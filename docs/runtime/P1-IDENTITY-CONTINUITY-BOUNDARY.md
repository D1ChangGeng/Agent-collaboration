# P1 identity continuity evidence boundary

`tools/runtime/p1_identity_continuity_probe.py` remains a component verifier.
It verifies authority request signatures, Node endpoint-registration signatures,
receiver receipt signatures, immutable logical identity, exact replay, boot
history and a bounded receiver SQLite readback. Its result is deliberately:

```text
status=component_only
gate_status=not_run
missing=[postgresql_live,sqlite_live,temporal_live,os_restart_live]
```

Those values are not renamed, emptied or accepted as a Gate result.

The `P1-IDENTITY-CONTINUITY` profile now has a separate Gate qualification in
`tools/runtime/p1_identity_continuity_scene.py`. Before the profile's ordinary
local `DeliveryDispatcher.dispatch` branch can run, the adapter provisions an
enrolled signed Node, Runtime and TLS receiver endpoint in PostgreSQL, then
queues the one Domain Message against that endpoint. The same Message,
operation, Delivery Attempt and dispatch identity pass through this sequence:

1. the old Core persists the real receiver `delivery.prepare` admission and
   signed receipt, then exits before the Domain dispatch marker;
2. the old receiver exits; the same enrolled Node is rotated from binding/boot
   revision 1 to 2, with a replacement Runtime and endpoint registered in the
   same PostgreSQL authority;
3. `submit_delivery` starts Workflow ID `acs-delivery/<operation_id>` and fixes
   its Run ID in PostgreSQL;
4. the first Temporal Worker exits before it recovers the prepared Attempt;
5. a replacement Worker calls `DeliveryDispatcher.recover_prepared`, preserving
   the original Attempt while using the signed replacement receiver binding;
6. the replacement receiver commits exactly one native dispatch in its SQLite
   journal and deliberately loses the recovery HTTP response;
7. signed readback completes the Domain projection, and byte-identical recovery
   replay returns the stored signed receipt without a second native dispatch.

The qualification passes only after reopening and rereading every authority:

- **PostgreSQL:** exactly one WorkItem, Message, Delivery Attempt, registered
  execution Attempt and Inbox projection; the two Node bindings, two Runtimes,
  two endpoint registrations, operations/events/Outbox, transport admissions,
  signed receiver receipts and provider Workflow/Run must all match.
- **receiver SQLite:** the same command, message, operation, Attempt and dispatch
  must have prepare/recover/readback history, boot/generation 1 to 2, signed
  receipts and exactly one native call.
- **Temporal:** a new client and workflow-only replay/query Worker read the exact
  Workflow ID and fixed Run using `describe`, `result` and `query`. That
  readback Worker registers no delivery activity and cannot dispatch again.
- **OS:** the old Core, old receiver, first Temporal Worker, submission process,
  replacement Worker and replacement receiver PIDs must be gone and distinct;
  both listener ports must be closed, TLS must be 1.3 with the registered
  certificate fingerprint, and private key files must be removed.

`gate_qualification` rejects `status=component_only`, any
`gate_status != passed`, a non-empty `missing` list, an absent layer readback or
an incomplete fault chain. Tests also reject changed Temporal Workflow/Run,
extra PG Node registration or Delivery Attempt, a missing Inbox row, duplicate
receiver native dispatch and a still-live old PID.

This adapter is the technical P1 scenario mechanism only. It does not execute
the formal 18-scenario Gate, run an independent review, supply a product-owner
decision, create an `AcceptedStateRevision`, publish a Release, or establish
cross-machine support.

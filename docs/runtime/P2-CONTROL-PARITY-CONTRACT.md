# P2 collaboration control parity Gate

Status: required P2 supplement; implementation support is determined only by
the matching Gate record. Gate ID:
`P2-CONTROL-PARITY`. Contract revision: `2026-09-25.1`.

This Gate follows `P2-MANAGEMENT-WORKFLOW` and precedes `P2-REVIEW`. It checks
the collaboration-control capability that the current supported Agent Hosts
can complete as a product workflow. The exact Gate scenario IDs live in
[gate-contract.json](gate-contract.json).
Each conclusion remains bound to the named source, Machine, Harness, Driver,
Provider, authenticated Profile and Grant, direction, Policy and expiry. Earlier
component or browser observations retain their original scope.

## Terms and authority

- A **program Harness** is a desktop or CLI Agent Harness, such as Codex,
  Codex CLI, OpenCode or OpenCode Desktop.
- A **Chat receiver** is a current, named Chat Agent Session hosted in a browser
  or desktop app. The first two validation paths are ChatGPT Web and ChatGPT
  Desktop Chat. Record the exact Host and interface used; MCP caller access
  alone does not establish a receiving Endpoint or a wakeable Session.
- A **Root Agent** is an authenticated external Session acting under an explicit
  `project_id` and current management Grant. It is not a new durable Domain
  identity. A user or authorized Root Agent decides whether and where work is
  handed off; the previous Engineer does not gain that decision by being the
  current owner.
- **Active wake** means an ACS-addressed Message causes the current target Chat
  Agent Session to start or resume a Turn without a new user prompt. Authority
  acceptance, Inbox persistence, MCP discovery, a browser notification, or a
  later user-initiated `check_inbox` do not by themselves prove active wake.

## Host applicability boundary

The current ChatGPT Web and ChatGPT Desktop component paths do not expose a
supported capability for an ACS message to start or resume a native Chat Turn
without a new user prompt. The observed component bridge can claim an Inbox
notification and return `SUBMITTED`; that result does not provide a native Turn
receipt. This is a Host product capability boundary, recorded in the private
Web/Chat continuity evidence, rather than an implementation prerequisite for
the current control parity Gate.

Inbox persistence and a later user-initiated read remain supported continuity
behaviors. They must not be registered as an active wake Endpoint. A future
Host with direct receive-and-wake evidence can add a separately versioned
scenario and Gate contract revision.

## `P2-CONTROL-HANDOFF-ACK`

The user or authorized Root Agent selects an existing, quiescent WorkItem and a
receiving AgentSlot already created with an appropriate Grant, current Session
and addressable Endpoint. The current owner is recorded as `from_agent_slot`;
it need not be the caller. The handoff carries exact Source state, context,
Evidence and unresolved items.

For `handoff_work(require_ack=true)`, commit the handoff intent and an addressed,
durable delivery/response expectation atomically, reusing the internal Message
and Outbox machinery or an equivalent single-authority transaction. Do not
implement this by making an uncoordinated second public MCP call. Return a
stable handoff identity, acknowledgement state `pending` and complete follow-up
handles without holding the call open indefinitely. B's authenticated,
structured accepted or rejected acknowledgement must bind the exact handoff,
Work revision and Source context. `target_inbox_committed` must precede B's
decision. Transport ACK, Inbox consumption and free-form text are not acceptance
of responsibility. The Root Agent observes the result and decides any retry,
withdrawal, reassignment or escalation; timeout remains pending.
Root-authorized assignment and B-confirmed handoff must be separately visible;
the system must not report confirmed handoff before B's acknowledgement.
Duplicate delivery, lost ACK and Session replacement must not create a second
handoff or silently broaden B's Grant.

The receiving collaborator uses `acknowledge_handoff` with the handoff handle,
expected handoff and Work revisions, Source digest, decision and reason. The
current `read_resource(handoff)` and `list_work` views expose assignment and
acknowledgement independently. Pending, rejected or withdrawn handoffs block
ordinary Work delivery and acceptance. Rejection keeps B assigned until Root
explicitly reassigns or cancels. `withdraw_handoff` lets Root close an unanswered
intent with expected revisions while retaining B's assignment and the historical
record; Root can then explicitly reassign. No timeout changes this state on its
own. A transport receipt or Inbox consumption never changes the handoff decision.

## Evidence and review boundary

Use the smallest real calls that prove each capability. Preserve raw MCP input
and output, current tools/list, authenticated identity and Grant, Domain and
target-Host readbacks, receipts, exact source and component versions, direction,
expiry and cleanup. Fault injection is required only for the recovery claim it
supports; an unrelated business task or Source write is not a substitute.
The current generic Gate validator still requires nonempty references for every
evidence field. Until it has reviewed applicability handling, do not invent a
fault or protected effect merely to satisfy that shape; keep this Gate blocked
when an evidence layer cannot be truthfully represented.

`submit_command` remains in the Operator Profile; Root Manager uses typed
project tools. Reviewers distinguish code/contract availability from Host capability
and independently inspect both the positive and denied paths. This Gate cannot
commit AcceptedStateRevision, merge, publish or replace the product owner's
final P2 decision.

The current machine tool catalog and implementation remain evidence of the
existing surface, not a claim that both capabilities have been delivered.
Their schemas and Profiles must change only with the corresponding
implementation and fresh tool-discovery/readback evidence.

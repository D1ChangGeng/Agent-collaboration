# P2 MCP collaboration and continuation contract

Status: adopted P2 implementation contract. Surface revision:
`acs-p2-mcp-workflow/3`.

This contract defines the direct MCP entry used by external Agents to configure
collaboration, discover eligible Harness capacity, send work, observe completion,
read durable results, recover Inbox state and control authorized activity. The
machine-readable companion is
[`p2-mcp-tool-contract.json`](p2-mcp-tool-contract.json).

## Responsibility boundary

External Agents decide team composition, task decomposition, review strategy and
the next intelligent action. ACS authenticates explicit decisions, applies
authorization and revision checks, persists collaboration state, performs
deterministic delivery and recovery, and returns evidence-bound observations.
MCP, CLI and HTTP map to the same Application Core and Domain state transitions.

The public MCP surface contains typed Agent tools and one advanced Domain-command
tool. Names use two or three familiar words and balance three signals: the action
the Agent intends, the corresponding human collaboration phrase, and the actual
Domain or Harness behavior. A typed argument carries the target object when one
operation contract applies uniformly across target kinds. Separate tools mark
different authorization, state-transition or result boundaries.

| Tool | Agent purpose | Primary result type |
|---|---|---|
| `setup_collaboration` | Persist an explicit Scope, AgentSlot, role, Grant, Policy and budget plan. | `collaboration_plan_result` |
| `find_harnesses` | Discover current Harness capacity eligible for a Scope, role and capability set. | `harness_capacity_page` |
| `send_message` | Submit addressed collaboration work and establish response tracking plus completion notification. | `message_submission` |
| `wait_for_response` | Perform a bounded `any` or `all` observation of response handles already being tracked. | `response_observation` |
| `read_resource` | Read a typed collaboration, Message, response, WorkItem, Evidence or Artifact handle. | `resource_snapshot` |
| `check_inbox` | Recover durable Messages and completion notifications for the authenticated AgentSlot. | `inbox_page` |
| `set_notification` | Enable or disable the completion notification attached to a response handle. | `notification_update_receipt` |
| `cancel_work` | Request cancellation of a durable WorkItem objective. | `work_item_cancellation_receipt` |
| `stop_attempt` | Request cancellation of one concrete Runtime Attempt. | `runtime_attempt_cancellation_receipt` |
| `submit_command` | Submit a fully formed Domain `SurfaceCommand` for operator, migration, conformance and advanced automation flows. | `domain_command_receipt` |

The existing `run` name is an advanced compatibility alias for
`submit_command`. Typed Agent workflows use the canonical names above.

`read_resource` accepts every authorized handle kind through `handle` and
`view`. `wait_for_response` accepts one or many response handles.
`set_notification` selects its subscription through `response_handle` and
`enabled`. `cancel_work` and `stop_attempt` remain separate because WorkItem
termination and Runtime Attempt interruption use different Grants, state
transitions, acknowledgements and effect readback.

## MCP exposure contract

`tools/list` exposes, for every canonical tool:

- `name` and `title`;
- a selection-oriented `description` that states the action, authoritative
  object, side effect and returned observation;
- a closed `inputSchema` with required fields, enum values, formats, defaults
  and `additionalProperties: false`;
- an `outputSchema` for `acs-mcp-result/2` whose `result_type` selects the exact
  `data` shape;
- `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`.

The description is sufficient for an Agent to distinguish dispatch, bounded
observation, durable read, Inbox recovery, notification control and execution
cancellation before it reads the input schema.

Example exposure for `send_message`:

```json
{
  "name": "send_message",
  "title": "Send collaboration message",
  "description": "Commit one collaboration Message, its delivery intent, response expectation and completion notification. Returns delivery state, the stable response handle and executable follow-up calls. Async is the default; sync adds one bounded observation of the same response handle.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": [
      "client_request_id",
      "work_item_id",
      "expected_work_item_revision",
      "target",
      "goal",
      "request",
      "constraints",
      "accepted_revision",
      "required_evidence",
      "deadline"
    ]
  },
  "outputSchema": {"$ref": "acs-mcp-result/2#message_submission"},
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  }
}
```

## Authentication and mutation context

Tenant, Authority, principal, Grant, caller Scope and caller AgentSlot come from
the authenticated MCP process binding. Handles identify resources inside that
binding. Mutating tools require a stable `client_request_id`, an expected
revision or equivalent precondition, and an absolute deadline. Replaying the
same request identity with the same canonical input returns the committed
disposition; changing canonical input produces a conflict.

## Result wire format

Every tool returns one native MCP result. `content` gives the calling Agent a
short status sentence. `structuredContent` carries the authoritative typed
payload. `isError` reports whether tool execution was accepted or rejected.

```json
{
  "content": [
    {
      "type": "text",
      "text": "Message message-01 accepted and queued until runtime-reviewer is idle; response response:message-01 will notify management-agent."
    }
  ],
  "structuredContent": {
    "schema_version": "acs-mcp-result/2",
    "result_type": "message_submission",
    "ok": true,
    "state": "accepted",
    "data": {},
    "follow_ups": [],
    "metadata": {}
  },
  "isError": false
}
```

A successful `structuredContent` contains:

| Field | Meaning |
|---|---|
| `schema_version` | Exact result-envelope version. |
| `result_type` | Discriminator selecting the `data` contract. |
| `ok` | `true` for an accepted state transition or completed observation. |
| `state` | Domain disposition such as `accepted`, `queued`, `pending`, `completed` or `applied`. |
| `data` | Result-type-specific facts. Fields unrelated to that result type are absent. |
| `follow_ups` | Executable next calls, each with `rel`, canonical `tool` and complete `arguments`. |
| `metadata` | Identity, revision, correlation, time, evidence class and expiry needed to interpret the observation. |

A rejected command or failed observation uses `result_type=problem`, `ok=false`,
an `error` object with stable `code`, `message`, `retryable`, `details` and
`conflict_revision`, and recovery calls in `follow_ups`. The MCP result sets
`isError=true` so the Harness can enter its tool-error recovery path.

## `setup_collaboration`

Use this tool after the calling Agent has chosen the collaboration topology. It
atomically authorizes and persists the supplied Scope, AgentSlots, roles, Grants,
Policies and budgets.

Required arguments: `client_request_id`, `expected_revision`, `deadline`,
`scope`, `agent_slots`. Optional arguments: inline `roles`, `grants`, `policies`
and `budgets` referenced by the plan.

```json
{
  "client_request_id": "setup-runtime-review-team-01",
  "expected_revision": 0,
  "deadline": "2026-09-22T16:00:00Z",
  "scope": {
    "scope_id": "route-runtime",
    "kind": "route",
    "policy_ref": "policy:runtime-p2/1"
  },
  "agent_slots": [
    {
      "agent_slot_id": "runtime-engineer-a",
      "role": "engineer",
      "grant_ref": "grant:runtime-engineer-a",
      "budget_ref": "budget:runtime-engineer-a",
      "harness_requirements": ["codex"]
    },
    {
      "agent_slot_id": "runtime-reviewer",
      "role": "reviewer",
      "grant_ref": "grant:runtime-reviewer",
      "budget_ref": "budget:runtime-reviewer",
      "harness_requirements": ["codex", "opencode"]
    }
  ]
}
```

The `collaboration_plan_result` data contains `operation`,
`collaboration_handle`, accepted `revision`, `scope_id` and `agent_slot_ids`.
Its `follow_ups` contains an exact `read_resource` call for the accepted plan.

## `find_harnesses`

Use this read-only tool to discover capacities whose Machine, Node, Runtime,
Driver, Endpoint, credential scope, capability observation and expiry meet the
assignment requirements.

Required arguments: `scope_id`, `required_capabilities`. Optional arguments:
`role`, `harness_kinds`, `require_current_until`, `cursor`, `limit`.

```json
{
  "scope_id": "route-runtime",
  "role": "reviewer",
  "required_capabilities": ["invoke", "inspect", "response_readback"],
  "harness_kinds": ["codex", "opencode"],
  "require_current_until": "2026-09-22T16:00:00Z",
  "cursor": null,
  "limit": 20
}
```

Each `harness_capacity_page.items[]` entry contains `capacity_handle`, Harness
and Driver versions, Machine and Node identity, supported directions,
capabilities, readiness, `evidence_class`, `observed_at` and `expires_at`.
Endpoint locators and credential values remain in their protected authorities.

## `send_message`

Use this tool for delegation, review requests, handoffs and other addressed
collaboration work. The Authority commits the Message, Outbox entry, response
expectation and completion notification in one operation.

Required arguments:

- `client_request_id`, `work_item_id`, `expected_work_item_revision`;
- `target.scope_id`, `target.agent_slot_id`;
- `goal`, `request`, `constraints`;
- `accepted_revision`, `required_evidence`, `deadline`.

Optional arguments and defaults:

```text
activation=invoke
delivery_policy=queue_until_idle
expect_response=true
response_mode=async
wait_until=response_received
wait_timeout_seconds=<required only when response_mode=sync>
```

```json
{
  "client_request_id": "delegate-runtime-check-01",
  "work_item_id": "work-runtime-check-01",
  "expected_work_item_revision": 3,
  "target": {
    "scope_id": "route-runtime",
    "agent_slot_id": "runtime-reviewer"
  },
  "goal": "Review the sealed runtime candidate",
  "request": "Check the bound source and evidence and return a structured verdict.",
  "constraints": ["read-only review", "bind the exact source baseline"],
  "accepted_revision": 2,
  "required_evidence": ["source_readback", "review"],
  "deadline": "2026-09-22T16:00:00Z"
}
```

Default asynchronous result:

```json
{
  "schema_version": "acs-mcp-result/2",
  "result_type": "message_submission",
  "ok": true,
  "state": "accepted",
  "data": {
    "operation": {
      "client_request_id": "delegate-runtime-check-01",
      "operation_id": "operation-01",
      "correlation_id": "correlation-01",
      "causation_id": "causation-01",
      "committed_at": "2026-09-22T15:30:00Z"
    },
    "message": {
      "message_id": "message-01",
      "handle": "message:message-01",
      "work_item_id": "work-runtime-check-01"
    },
    "delivery": {
      "state": "queued_for_idle",
      "receipt_high_water": "accepted_by_authority",
      "target_scope_id": "route-runtime",
      "target_agent_slot_id": "runtime-reviewer",
      "target_activity": "busy",
      "next_transition": "dispatch_when_idle"
    },
    "response": {
      "expected": true,
      "mode": "async",
      "handle": "response:message-01",
      "state": "pending",
      "completion_condition": "response_received"
    },
    "notification": {
      "enabled": true,
      "state": "tracking",
      "subscription_revision": 1,
      "reply_to_agent_slot_id": "management-agent",
      "delivery_policy": "queue_until_idle"
    }
  },
  "follow_ups": [
    {
      "rel": "read_response",
      "tool": "read_resource",
      "arguments": {"handle": "response:message-01", "view": "result", "observe": true}
    },
    {
      "rel": "await_response",
      "tool": "wait_for_response",
      "arguments": {
        "handles": ["response:message-01"],
        "mode": "all",
        "until": "response_received",
        "timeout_seconds": 120
      }
    },
    {
      "rel": "set_notification",
      "tool": "set_notification",
      "arguments": {
        "client_request_id": "set-notification-message-01-01",
        "response_handle": "response:message-01",
        "enabled": false,
        "expected_revision": 1,
        "reason": "The parent workflow will observe the response directly.",
        "deadline": "2026-09-22T16:00:00Z"
      }
    }
  ],
  "metadata": {
    "scope_id": "route-runtime",
    "caller_agent_slot_id": "management-agent",
    "work_item_revision": 3,
    "accepted_revision": 2,
    "deadline": "2026-09-22T16:00:00Z",
    "observed_at": "2026-09-22T15:30:00Z",
    "evidence_class": "authority_committed"
  }
}
```

`response_mode=sync` performs the same commit and then invokes the equivalent
bounded `wait_for_response` observation. Timeout returns `state=pending` with the
same Message and response identities. Completion, notification and later reads
continue from those identities.

## `wait_for_response`

Use this read-only observation tool when the initiating Agent chooses to pause
for responses already tracked by `send_message`. It holds no database
transaction during the wait.

Required arguments: `handles`, `mode`, `until`, `timeout_seconds`. `mode` is
`any` or `all`.

```json
{
  "handles": ["response:message-01", "response:message-02"],
  "mode": "all",
  "until": "response_received",
  "timeout_seconds": 120
}
```

The `response_observation` data contains `condition`, `mode`,
`satisfied_handles`, `pending_handles`, `terminal_handles`,
`completion_revision` and `notification_states`. Every satisfied handle has an
exact `read_resource` call in `follow_ups`; every pending observation can return
an exact repeat `wait_for_response` call. Reaching the condition records the caller
AgentSlot's completion observation. The durable Inbox item remains recoverable,
and its native wake state converges to observed.

## `read_resource`

Use this common read surface with a typed handle returned by another ACS tool.

Required argument: `handle`. Optional arguments: `view`, `observe`, `cursor`,
`limit`, `max_inline_bytes`. Views are `summary`, `result`, `evidence`, `history`
and `content`.

```json
{
  "handle": "response:message-01",
  "view": "result",
  "observe": true,
  "cursor": null,
  "limit": 50,
  "max_inline_bytes": 16384
}
```

The `resource_snapshot` data contains resource `handle`, `kind`, `state`,
`revision`, observation metadata, typed `relations`, bounded `content`,
`evidence_handles`, `unresolved_items` and `next_cursor`. Large content returns
an Artifact handle, SHA-256 digest, media type and size. An owner read with
`observe=true` records the completion observation and converges with any queued
completion notification.

## `check_inbox`

Use this read-only tool at startup, reconnect and recovery. The cursor belongs
to the authenticated AgentSlot and survives Harness Session replacement.

All arguments are optional: `cursor`, `limit`, `states`, `kinds`.

```json
{
  "cursor": null,
  "limit": 50,
  "states": ["available", "queued_for_idle"],
  "kinds": ["message", "response_available", "recovery_required"]
}
```

Each `inbox_page.items[]` entry contains `notification_id`, `kind`, `state`,
Message and response handles, `completion_revision`, delivery observation and an
executable `read_resource` follow-up. Listing preserves item state; observation
is recorded by the corresponding resource read.

## `set_notification`

`send_message` creates automatic completion notification when a response is
expected. This tool changes that subscription explicitly.

Required arguments: `client_request_id`, `response_handle`, `enabled`,
`expected_revision`, `reason`, `deadline`.

The `notification_update_receipt` data contains `operation`, `response_handle`,
the new `subscription_revision`, `notification_state` and independent
`response_state`. Its follow-up reads the response summary. Disabling a
notification leaves response collection, response state and resource reads
active.

## `cancel_work`

Use this tool to end the durable work objective identified by a WorkItem.
Required arguments: `client_request_id`, `work_item_id`, `expected_revision`,
`reason`, `deadline`.

The `work_item_cancellation_receipt` data contains `operation`, WorkItem identity,
revision and state, plus each related Runtime Attempt and its current state.
Follow-up calls read the WorkItem and any effects whose outcome requires
authoritative readback.

## `stop_attempt`

Use this tool for one concrete execution attempt. Required arguments:
`client_request_id`, `runtime_attempt_id`, `expected_revision`, `reason`,
`deadline`.

The `runtime_attempt_cancellation_receipt` data contains `operation`, Attempt
identity, revision and state, Driver acknowledgement, and `effect_state`.
Ambiguous external effects return a `read_resource` follow-up for their
authoritative markers before another Attempt can be admitted.

## `submit_command`

This advanced tool accepts one complete versioned Domain `SurfaceCommand` as
`request`. It returns `domain_command_receipt` with `operation`, canonical
`disposition` and `resource_handles`. Operator, migration, conformance and
advanced automation clients use this surface when they already own the Domain
command schema. The `run` compatibility alias accepts the same input and returns
the same bytes.

## Delivery, waiting and wake behavior

An initiating Agent keeps using authorized tools while response handles are
pending. Response tracking is a Domain state dimension independent of Harness
turn state. Async `send_message` creates durable response tracking and completion
notification in the same Authority commit, then returns control to the Agent.

The default `queue_until_idle` policy applies to work Messages and completion
notifications. Current Session activity comes from an unexpired Driver/Node
observation:

- `idle` admits native invocation;
- `busy` commits the Inbox item and schedules dispatch after an idle observation;
- `offline` retains delivery for the next current Session binding;
- `unknown` retains delivery until activity is observed again.

Completion notification uses a stable identity derived from response handle and
completion revision. Projection retry, duplicate native result, Node restart and
Temporal retry converge on one notification and one native invocation. The
initiating AgentSlot owns the subscription, so Session replacement routes the
notification to its current binding. The notification tells the Agent which
response completed and supplies the exact `read_resource` call.

## High-level workflow commands

P2 delivers reusable command documents that call the canonical tools and retain
their structured results:

- `acs-collaborate.command.md` applies an explicit topology, discovers capacity,
  creates WorkItems and submits asynchronous work;
- `acs-review.command.md` dispatches an exact-baseline review and binds its
  result and evidence handles;
- `acs-results.command.md` recovers Inbox state and reads completed results;
- `acs-cancel.command.md` applies notification, WorkItem or Runtime Attempt
  control through the corresponding typed tool;
- `acs-status.command.md` presents observed collaboration, delivery, response
  and recovery state with evidence class and validity.

## P2 acceptance

The `P2-MCP-WORKFLOW` Gate follows `P2-OPENCODE`. It exercises canonical tool
discovery and invocation from real Codex and OpenCode clients against the same
exact source and Domain Authority. Evidence includes `tools/list` descriptions,
input and output schemas, native result bytes, Message/response/notification
state, Driver/Node readback, Session activity transitions, completion delivery,
Artifact and Evidence reads, typed cancellation authority, Temporal recovery and
zero unresolved items.

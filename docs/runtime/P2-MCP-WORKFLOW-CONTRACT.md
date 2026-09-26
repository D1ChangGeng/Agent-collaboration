# P2 MCP collaboration and continuation contract

Status: adopted P2 implementation contract. Surface revision:
`acs-p2-mcp-workflow/1`.

This contract defines the direct MCP entry used by external Agents to configure
collaboration, discover eligible Harness capacity, send work, observe completion,
read durable results, recover Inbox state and cancel authorized activity. The
machine-readable companion is
[`p2-mcp-tool-contract.json`](p2-mcp-tool-contract.json).

## Boundary

External Agents decide team composition, task decomposition, review strategy and
the next intelligent action. The MCP surface accepts explicit decisions and maps
them to the shared Application Core. MCP, CLI and HTTP use the same Domain
commands, authorization model and state transitions.

The ordinary Agent surface consists of:

| Tool | Purpose |
|---|---|
| `collaboration_apply` | Atomically create or revise an explicitly supplied Scope, AgentSlot, Role, Grant and Policy plan. |
| `harnesses` | Read currently eligible Harness capacities and the evidence that bounds their use. |
| `send` | Commit a collaboration Message and its response tracking. Asynchronous response handling is the default; bounded synchronous observation is optional. |
| `await` | Observe an existing response handle until a receipt or terminal condition is reached. |
| `read` | Read a typed handle for a Message, response, WorkItem, Evidence, Artifact or collaboration plan. |
| `inbox` | List durable notifications and Messages addressed to the authenticated AgentSlot. |
| `cancel` | Apply an authorized cancellation to a subscription, WorkItem or Runtime Attempt. |

The existing `run` tool remains the strict low-level command surface for Node,
operator, migration, test and advanced automation flows.

## Common authenticated context

Tenant, Authority, principal, Grant, caller Scope and caller AgentSlot come from
the authenticated MCP process binding. A request cannot replace them. A handle
is an identifier, not a credential.

Every mutating tool requires a stable `client_request_id`, expected revision or
equivalent precondition, and an absolute deadline. Reusing a request identity
with different canonical input is a conflict.

## Surface invariants

- `send` establishes response tracking and notification atomically with Message
  submission when a response is expected.
- Asynchronous response handling returns after Authority commit and leaves the
  initiating Agent free to continue authorized work.
- Synchronous response handling is the same submission followed by bounded
  observation of the returned response handle.
- Every result supplies the stable handle, current state, required metadata and
  exact follow-up tool arguments.
- `read` is the common data-access surface for collaboration, Message, response,
  WorkItem, Evidence and Artifact handles.
- Completion is notified through the normal Inbox/Outbox and Message path.
- Session activity is an expiring observation; `queue_until_idle` is the
  default when current idle capacity is not established.
- Wait state, Harness activity and WorkItem execution remain independent state
  dimensions.

## `collaboration_apply`

Description:

> Apply one explicit collaboration topology under the authenticated Management
> scope. The supplied plan names every Scope, AgentSlot, role, Grant, Policy and
> budget; the Core performs no team-composition reasoning.

Input:

```json
{
  "schema_version": "acs-mcp-collaboration-apply/1",
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

Result:

```json
{
  "schema_version": "acs-mcp-operation-result/1",
  "ok": true,
  "state": "applied",
  "operation": {
    "client_request_id": "setup-runtime-review-team-01",
    "operation_id": "operation-...",
    "revision": 1,
    "committed_at": "2026-09-22T15:30:00Z"
  },
  "resource": {
    "handle": "collaboration:route-runtime",
    "kind": "collaboration",
    "scope_id": "route-runtime",
    "agent_slot_ids": ["runtime-engineer-a", "runtime-reviewer"]
  },
  "read": {
    "tool": "read",
    "arguments": {"handle": "collaboration:route-runtime", "view": "summary"}
  },
  "error": null
}
```

## `harnesses`

Description:

> Return current Harness capacities whose Machine, Node, Runtime, Driver,
> Endpoint, credential scope, capability observation and expiry satisfy the
> requested Scope and role.

Input:

```json
{
  "schema_version": "acs-mcp-harnesses/1",
  "scope_id": "route-runtime",
  "role": "reviewer",
  "required_capabilities": ["invoke", "inspect", "response_readback"],
  "harness_kinds": ["codex", "opencode"],
  "cursor": null,
  "limit": 20
}
```

Result items contain logical capacity identity, Harness/Driver versions,
Machine/Node identity, supported directions, capability expiry, evidence class
and readiness. Locator values and credential material remain operator-owned.

Result:

```json
{
  "schema_version": "acs-mcp-harness-list-result/1",
  "ok": true,
  "items": [
    {
      "capacity_handle": "harness:runtime-reviewer:codex",
      "harness_kind": "codex",
      "harness_version": "0.155.0",
      "driver_version": "driver-...",
      "machine_id": "linux-1302-1",
      "node_id": "node-...",
      "capabilities": ["invoke", "inspect", "response_readback"],
      "directions": ["receive", "respond"],
      "readiness": "eligible",
      "evidence_class": "directly_verified",
      "expires_at": "2026-09-22T16:00:00Z"
    }
  ],
  "next_cursor": null,
  "error": null
}
```

## `send`

Description:

> Commit one collaboration Message, durable Outbox entry, response expectation
> and completion notification policy. Return after Authority commit by default.
> When `response_mode` is `sync`, observe the same response handle for a bounded
> interval.

Input:

```json
{
  "schema_version": "acs-mcp-send/1",
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
  "activation": "invoke",
  "delivery_policy": "queue_until_idle",
  "expect_response": true,
  "response_mode": "async",
  "wait_until": "response_received",
  "wait_timeout_seconds": null,
  "required_evidence": ["source_readback", "review"],
  "deadline": "2026-09-22T16:00:00Z"
}
```

Defaults:

```text
activation=invoke
delivery_policy=queue_until_idle
expect_response=true
response_mode=async
wait_until=response_received
```

`response_mode=sync` accepts a bounded `wait_timeout_seconds`. A bounded timeout
returns a pending result while delivery, response collection and completion
notification continue under the original Message identity.

Asynchronous result template:

```json
{
  "schema_version": "acs-mcp-operation-result/1",
  "ok": true,
  "state": "accepted",
  "operation": {
    "client_request_id": "delegate-runtime-check-01",
    "message_id": "message-...",
    "operation_id": "operation-...",
    "correlation_id": "correlation-...",
    "causation_id": "causation-...",
    "committed_at": "2026-09-22T15:30:00Z"
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
    "handle": "response:message-...",
    "state": "pending",
    "completion_condition": "response_received",
    "automatic_notification": true,
    "reply_to_agent_slot_id": "management-agent"
  },
  "read": {
    "tool": "read",
    "arguments": {"handle": "response:message-...", "view": "result", "observe": true}
  },
  "await": {
    "tool": "await",
    "arguments": {"handle": "response:message-...", "until": "response_received", "timeout_seconds": 120}
  },
  "metadata": {
    "work_item_id": "work-runtime-check-01",
    "work_item_revision": 3,
    "accepted_revision": 2,
    "deadline": "2026-09-22T16:00:00Z",
    "observed_at": "2026-09-22T15:30:00Z"
  },
  "error": null
}
```

Synchronous completion returns the same structure with `state=completed`, the
same response handle and `response.state=completed`. The `read` instruction
remains authoritative for result content. A synchronous caller that observes
completion records the response as observed and suppresses a pending completion
notification before native dispatch.

## `await`

Description:

> Perform a bounded observation of one or more existing response handles. The
> durable response expectation, notification and delivery continue independently
> of the MCP connection.

Input:

```json
{
  "schema_version": "acs-mcp-await/1",
  "handles": ["response:message-..."],
  "mode": "all",
  "until": "response_received",
  "timeout_seconds": 120
}
```

`mode` is `any` or `all`. A completed result lists satisfied and pending
handles and supplies exact `read` calls. A pending result supplies the current
receipt high-water marks, automatic-notification state and the same read calls.
The implementation holds no PostgreSQL transaction while waiting.

Result:

```json
{
  "schema_version": "acs-mcp-operation-result/1",
  "ok": true,
  "state": "completed",
  "operation": {"operation_id": "await-...", "completion_revision": 1},
  "delivery": null,
  "response": {
    "mode": "sync",
    "satisfied_handles": ["response:message-..."],
    "pending_handles": [],
    "automatic_notification": false
  },
  "read": [
    {"tool": "read", "arguments": {"handle": "response:message-...", "view": "result", "observe": true}}
  ],
  "await": null,
  "metadata": {"condition": "response_received", "observed_at": "2026-09-22T15:45:00Z"},
  "error": null
}
```

## `read`

Description:

> Read an authorized typed handle and return bounded metadata, relations,
> content references and evidence references. An owner read with `observe=true`
> records the completion as observed and can suppress a queued notification.

Input:

```json
{
  "schema_version": "acs-mcp-read/1",
  "handle": "response:message-...",
  "view": "result",
  "observe": true,
  "cursor": null,
  "limit": 50,
  "max_inline_bytes": 16384
}
```

Views are `summary`, `result`, `evidence`, `history` and `content`. Large content
is returned as an Artifact handle with digest and media type. Repeated reads are
idempotent.

Result:

```json
{
  "schema_version": "acs-mcp-read-result/1",
  "ok": true,
  "resource": {
    "handle": "response:message-...",
    "kind": "response",
    "state": "completed",
    "revision": 4,
    "observed_at": "2026-09-22T15:45:00Z"
  },
  "metadata": {
    "message_id": "message-...",
    "operation_id": "operation-...",
    "work_item_id": "work-runtime-check-01",
    "receipt_high_water": "response_received",
    "completion_revision": 1,
    "native_outcome": "completed"
  },
  "content": {
    "inline": null,
    "artifact_handle": "artifact:sha256-...",
    "sha256": "...",
    "media_type": "application/json"
  },
  "evidence_handles": ["evidence:..."],
  "unresolved_items": [],
  "next_cursor": null,
  "error": null
}
```

## `inbox`

Description:

> List durable Messages and completion notifications for the authenticated
> AgentSlot. The cursor survives Harness Session replacement.

Input:

```json
{
  "schema_version": "acs-mcp-inbox/1",
  "cursor": null,
  "limit": 50,
  "states": ["available", "queued_for_idle"],
  "kinds": ["message", "response_available", "recovery_required"]
}
```

Each item includes its stable handle, Message identity, delivery state,
completion revision and exact `read` call. Listing is non-destructive. Reading
with observation records the owner acknowledgement.

Result:

```json
{
  "schema_version": "acs-mcp-inbox-result/1",
  "ok": true,
  "items": [
    {
      "notification_id": "notification:wait-...:1",
      "kind": "response_available",
      "state": "available",
      "message_id": "message-...",
      "response_handle": "response:message-...",
      "completion_revision": 1,
      "read": {"tool": "read", "arguments": {"handle": "response:message-...", "view": "result", "observe": true}}
    }
  ],
  "next_cursor": null,
  "error": null
}
```

## `cancel`

Description:

> Apply one explicit cancellation action to a typed handle with current
> revision and authorization checks.

Input:

```json
{
  "schema_version": "acs-mcp-cancel/1",
  "client_request_id": "cancel-runtime-check-01",
  "handle": "response:message-...",
  "action": "stop_notification",
  "expected_revision": 4,
  "reason": "Result will be reviewed through the parent workflow",
  "deadline": "2026-09-22T16:00:00Z"
}
```

Actions are `stop_notification`, `cancel_work_item` and
`cancel_runtime_attempt`. Each action uses a distinct Grant permission. The
result reports subscription, WorkItem and Runtime Attempt states independently.

Result:

```json
{
  "schema_version": "acs-mcp-operation-result/1",
  "ok": true,
  "state": "applied",
  "operation": {"client_request_id": "cancel-runtime-check-01", "operation_id": "operation-...", "revision": 5},
  "delivery": null,
  "response": {
    "handle": "response:message-...",
    "notification_state": "stopped",
    "work_item_state": "executing",
    "runtime_attempt_state": "running"
  },
  "read": {"tool": "read", "arguments": {"handle": "response:message-...", "view": "summary", "observe": false}},
  "await": null,
  "metadata": {"action": "stop_notification", "observed_at": "2026-09-22T15:45:00Z"},
  "error": null
}
```

## Delivery and completion behavior

An initiating Agent can continue using any authorized tool while responses are
pending. Response tracking is a Domain state dimension and does not change the
Harness turn state.

The default delivery policy is `queue_until_idle` for both work Messages and
completion notifications. Current Session activity is obtained from an
unexpired Driver/Node observation. `idle` permits invocation; `busy` commits the
Inbox item and waits; `offline` waits for a current Session binding; `unknown`
remains queued until a fresh observation is available. Steering an active turn
is an explicitly named Policy capability.

Completion notification uses a stable Message identity derived from response
handle and completion revision. Projection retries, duplicate native results,
Node restart and Temporal retry therefore converge on one notification and one
native invocation. The initiating AgentSlot owns the subscription, and its
current Session binding receives the notification after replacement.

## High-level workflow commands

P2 delivers reusable command documents for:

- `acs-collaborate.command.md` — apply an explicit topology, discover capacity,
  create WorkItems and submit asynchronous work;
- `acs-review.command.md` — dispatch an exact-baseline review and bind its
  result/evidence handles;
- `acs-results.command.md` — recover Inbox state and read completed results;
- `acs-cancel.command.md` — apply the selected subscription, WorkItem or Runtime
  Attempt cancellation;
- `acs-status.command.md` — present observed collaboration, delivery, response
  and recovery state with its evidence class and validity.

The command documents call the public tools above and preserve their structured
results. They do not contain team-selection reasoning or embedded credentials.

## P2 acceptance

The `P2-MCP-WORKFLOW` Gate follows `P2-OPENCODE`. It exercises the public tools
from real Codex and OpenCode clients against the same exact source and Domain
Authority. Evidence includes tool discovery, authenticated command input,
structured result bytes, Message/Wait/notification state, Driver/Node readback,
Session activity transitions, completion delivery, Artifact/Evidence reads,
cancellation authority, Temporal recovery and zero unresolved items.

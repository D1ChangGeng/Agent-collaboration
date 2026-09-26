# Runtime Driver and MCP interface contract

Status: adopted implementation decisions. Contract revision: `2026-09-11.1`.
Authority: [Runtime adoption contract](UPGRADE-CONTRACT.md).
Reviewed repository baseline: `7167d5948a7b6a7e8641410625f2e0932e25ecfd`.
Source evidence is `source-reviewed`; lifecycle, MCP interoperability and E2E
conformance remain `not_run` until their named Gate evidence is recorded.

## Versioned integration profiles

Codex uses App Server; OpenCode uses its native HTTP API. Bind capabilities to
executable/version/schema digests; Node records effective settings before dispatch.

| Profile | Harness or SDK version | Fixed official source revision |
|---|---|---|
| Codex / Windows | `0.152.1` | [`5adb68a49933ae446bf11935662c83dba55a0804`][c152] |
| Codex / Linux | `0.153.2` | [`657a993cbee87acf52d14b758ce49dbd46d1b8eb`][c153] |
| OpenCode / Windows | `1.18.27` | [`4b7e19e315cca414121ba1d61523fef74bb3ae8b`][o127] |
| OpenCode / Linux | `1.18.30` | [`3104c1428ec91f809e5ab86631300de41eb6952e`][o130] |
| MCP Python reference SDK | `mcp==2.2.0` | [`9972c21aa42054fb1450c5fc614761ed11847ec6`][m220] |

Generate Codex schemas from each binary; capture OpenCode's served OpenAPI and
health/version response. Unknown versions/methods require a new capability probe.
Each deployed profile needs executable and conformance evidence; documentation explains the interface.

## Lifecycle mapping

`spawn` separates process acquisition, native session creation and model-turn authorization.

| Driver operation | Codex App Server | OpenCode native HTTP |
|---|---|---|
| `spawn` | Node starts an owned App Server; connection sends `initialize`, then `initialized`; `thread/start` returns `thread.id` and `thread.sessionId`. | Node starts an owned `opencode --pure serve`; checks `/global/health` and schema; `POST /session` returns the native session ID. |
| `attach` | Connect to an authorized endpoint; `thread/read` inspects; `thread/resume` joins/subscribes to the known thread when active access is required. | Bind the authorized endpoint and known `sessionID`; read `/session/:id`, `/session/status`, `/session/:id/message` and subscribe to `/event`. |
| `invoke` | `turn/start` carries `threadId`, structured input and `clientUserMessageId`; persist returned `turn.id` and consume turn/item events. | `POST /session/:id/prompt_async` carries a pre-journaled native `messageID`, allowed agent/model and parts; read back `/session/:id/message/:messageID`. |
| `resume` | `thread/resume` restores context/subscription; further generation requires an authorized `turn/start`. | Restore endpoint/binding, read retained messages/status, then submit an authorized prompt to the retained session ID. |
| `cancel` | `turn/interrupt` uses the exact current `threadId` and nonempty `turnId`; collect the response and terminal interrupted state. | `POST /session/:id/abort`; serialize against invocation/replacement because this API has no expected turn/message parameter. |
| `terminate` | Node performs bounded shutdown and process-tree termination for exclusively owned capacity; records actual exits and remaining processes. | Apply the same ownership rule to the server and its descendants; account for every session hosted in that process. |
| `inspect` | `thread/read` with `includeTurns:true`, `thread/loaded/list`, status/events and Node process observations establish separate context and process facts. | Session detail, messages, status, children/events and Node process observations establish separate context and process facts. |

Codex `turn/start` calls `start_or_steer_turn`; an active turn can receive steering.
Serialize operations and verify status; declare explicit steering semantics. [Source][cturn]
OpenCode saves the user message and enters its loop; native message IDs provide
correlation, not a proven exactly-once guarantee. [Source][oprompt]

## Ownership, binding and replacement

Use exclusive Node-owned capacity for first termination conformance; record
`exclusive_owned` or `shared_attached`. Hard termination requires proven exclusive ownership.
Use a Windows Job Object, Linux cgroup or equivalent containment; verify descendant
cleanup, escaped children and remaining effects. Preserve unrelated shared-endpoint work.

A binding records ID/revision, AgentSlot, Attempt, Node boot/incarnation, endpoint,
process/start identity, ownership, native thread/session/turn/message IDs and version/schema/config digests.
Operations retain command/operation/message IDs, payload digest, authorization
lineage, deadline, observation time/expiry and raw evidence references.
Serialize invoke/cancel/replacement across recovery. Shared-session mutation requires
verified single-writer control; otherwise expose attach/inspect only.
Replacement increments revision/generation and retains retired bindings. Late receipts
belong to the original Attempt and cannot advance replacement state or resource authority.

Record archive/detach/context unload and process shutdown independently. Codex archive
can proceed after shutdown timeout; unsubscribe removes a subscription. [Source][cthread]
OpenCode archive updates metadata; delete removes data; ACP close releases its binding
and aborts backing work. Process termination needs Node evidence. [Session source][osession], [ACP source][oacp]

## Receipt semantics and uncertain outcomes

| Receipt | Required evidence |
|---|---|
| `accepted_by_authority` | Domain transaction committed authorization, transition, dedup, event and Outbox. |
| `target_inbox_committed` | Target Node's durable mailbox committed the authorized packet and identity. |
| `runtime_dispatched` | Node journal binds the actual outbound request to endpoint, process and operation. |
| `runtime_acknowledged` | Native response/read-back identifies the submitted turn/message and matching content; preserve the underlying ACK type. |
| `response_received` | Correlated final assistant output, native terminal status and read-back; preserve failure/interruption. |

OpenCode HTTP 204 acknowledges scheduling; require matching message read-back
before upgrading its evidence. [Source][ohttp] Codex's ordinary interrupt response
waits for `TurnAborted`; empty-turn startup acknowledges submission. Use the
nonempty exact-turn path and retain terminal evidence. [Source][cturn]

Journal intent before spawn/request. Lost ACKs enter `uncertain`; reconcile before retry.
OpenCode create-time metadata carries operation ID. Codex has no reviewed client-supplied
create ID: journal process labels and before/after native IDs; adopt only a unique verified match.
Ambiguity requires isolation/read-back before replacement. Domain dedup remains authoritative;
RPC/native correlation, acceptance and external-effect read-back retain distinct records.

## Delegation, source and sandbox isolation

Apply the [Source and Sandbox contract](SANDBOX-CONTRACT.md) for the conditional Reference Profile, exact permission fields and real isolation conformance.

Launch Codex with `--disable multi_agent --disable multi_agent_v2`; capture both
effective features as false, prevent overrides and verify native child creation is disabled.
Launch OpenCode with `--pure`; apply agent `permission.task="deny"` and final session
rule `{"permission":"task","pattern":"*","action":"deny"}`; read effective permissions.
Canonical input uses approved text/file parts and agent/model choices. Reject arbitrary
`tools`, agent/subtask parts and command surfaces: `tools` can replace session permissions;
agent parts can select a task permission-bypass path. [Prompt source][oprompt], [Task source][otask]
Check effective tool catalog, task rejection and native children. External plugins,
custom tools and MCP endpoints require an explicit profile allowlist.

Each parallel Engineer uses an authorized separate worktree/sandbox, source baseline,
root allowlist and resource claim. Validate cwd, repository, outputs and source grants at dispatch.
Resolve credentials through secret references; keep values outside packets, logs and source.
Combine Harness sandbox, OS containment and Effect-gateway fencing. Unfenceable
resources require confirmed old-owner isolation. Preserve user work and retain output
commit/tree/diff/untracked manifests for source/artifact read-back.

## MCP entry point

Use `MCPServer` from `mcp.server`; lock `mcp==2.2.0` and matching `mcp-types==2.2.0`.
Let the SDK implement transport/wire behavior. The initial profile uses the actual
client's negotiated legacy revision; exercise `2025-06-18` and `2025-11-25` independently.
Record version/capabilities. `2026-07-28` has a distinct per-request protocol path
and needs separate conformance. [SDK version registry][mversions]
MCP/CLI/HTTP use one authenticated application service and canonical command schema.
Trusted transport supplies identity/Grant; validate tool name, payload, idempotency,
expected revision and deadline. Return structured receipts and query references.
SDK v2 Python fields use snake_case; wire dumps use `by_alias=True`. [Guide][mmigrate]
MCP disconnect/request cancellation preserves committed Domain operations; business
cancel requires an authorized command. Validate real SDK initialization/errors at the endpoint.

## Executable conformance matrix

All scenarios below are `not_run`. Bind evidence to [the Gate contract](gate-contract.json).
Run actual Harnesses and Domain/Node/Provider; fixture evidence remains fixture-scoped.
Capture requests, IDs, exits, faults and native/effect read-back with digests,
source baseline, credential scope and profile versions.

| ID | Exercise or injected fault | Required result |
|---|---|---|
| V1 | Probe each listed installed version and generate/capture schema. | Version/schema/launch evidence; unsupported capabilities fail closed. |
| L1 | Run spawn, attach, invoke, resume, cancel, terminate and inspect. | Native identity, ACK, terminal state and actual process observations for each action. |
| L2 | Run two sessions in a shared server; cancel one and request its termination. | Other session progresses; ownership blocks unsafe shared-process termination. |
| L3 | Submit concurrent invokes and race cancel with replacement. | Durable per-binding serialization; no unintended steer or cancellation of replacement work. |
| D1 | Repeat a command through MCP/HTTP/CLI; reuse its key with altered input. | One logical operation for identical input; canonical-input conflict otherwise. |
| D2 | Crash Node after OS spawn but before spawn-result journaling. | Reconcile operation labels, start identity and process tree; no blind duplicate spawn. |
| D3 | Drop native session-create response after provider creation. | Unique metadata/native read-back permits adoption; ambiguous Codex creation remains uncertain. |
| D4 | Drop invoke ACK and event connection after submission. | Correlated turn/message read-back; recovery produces no duplicate model invocation. |
| R1 | Replace a binding; deliver old ACK/output and attempt an old-owner effect. | Retired provenance retained; replacement state unchanged; Effect gateway rejects stale owner. |
| R2 | Restart Node/Harness during activity; archive/unsubscribe during cleanup. | Mailbox/binding recovery; archive/detach never substitutes for actual shutdown evidence. |
| I1 | Request native delegation and attempt config, tools and agent-part overrides. | Effective restrictions hold; actual task attempts rejected and native child inventory matches. |
| S1 | Attempt another worker's source/output path and a stale resource write. | Sandbox/source grants and resource fencing reject access at their actual boundaries. |
| M1 | Exercise legacy handshake, malformed/unknown tools, unauthorized calls and disconnect after commit. | SDK interoperability, authenticated rejection, stable dedup and queryable committed operation. |

[c152]: https://github.com/openai/codex/tree/5adb68a49933ae446bf11935662c83dba55a0804
[c153]: https://github.com/openai/codex/tree/657a993cbee87acf52d14b758ce49dbd46d1b8eb
[o127]: https://github.com/anomalyco/opencode/tree/4b7e19e315cca414121ba1d61523fef74bb3ae8b
[o130]: https://github.com/anomalyco/opencode/tree/3104c1428ec91f809e5ab86631300de41eb6952e
[m220]: https://github.com/modelcontextprotocol/python-sdk/tree/9972c21aa42054fb1450c5fc614761ed11847ec6
[cturn]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/app-server/src/request_processors/turn_processor.rs
[cthread]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/app-server/src/request_processors/thread_processor.rs
[ohttp]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts
[osession]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/session.ts
[oprompt]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/prompt.ts
[otask]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/task.ts
[oacp]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/acp/service.ts
[mversions]: https://github.com/modelcontextprotocol/python-sdk/blob/9972c21aa42054fb1450c5fc614761ed11847ec6/src/mcp-types/mcp_types/version.py
[mmigrate]: https://py.sdk.modelcontextprotocol.io/migration/

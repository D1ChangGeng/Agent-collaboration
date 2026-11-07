# WP08 Orca host port map

Source inspection date: 2026-11-06.

The inspected clone was `D:\Chatgpt\Agent-collaboration\.tmp\orca-cross-harness-pinned`, at exact HEAD `53fbfded41b8b0462d7ccd029475f89d12aa9bf5`. `git status --short` / `--porcelain` returned no entries at the inspection checkpoints. This was a read-only source audit: no Orca edits, tests, DB access, host operations or network calls. Paths below are relative to that pinned clone.

This map is source evidence and an implementation route, not host qualification or evidence that a provider is installed. Its scope follows devpack `docs/10_ORCA_UI_READINESS.md` and `contracts/orca_integration.ts`.

## Existing routes

| Integration port | Existing source route | Bridge requirement |
| --- | --- | --- |
| `capabilities`, receiver `describe` | `src/main/runtime/rpc/methods/structured-agent-session-options-read.ts`: `agentSession.options`, `modelCatalog`, `commands`; host `readCommands` distinguishes unavailable from an authoritative empty catalog. | Publish an authenticated descriptor of the actual host/session/generation and observed operations. Do not derive Native capabilities from function presence or provider brand. |
| `listSessions` | `src/main/runtime/rpc/methods/session-tabs.ts`: `session.tabs.list/listAll`; `ai-vault.ts`: `aiVault.listSessions` for provider history. | Filter by separately authorized host/workspace scope and provide bounded paging. Public `workspace.list` alone is not a Native-session catalog. |
| `read` | `structured-agent-session.ts`: `agentSession.history`; `native-chat.ts`: `nativeChat.readSession`. | Preserve native row identity, blocks and provenance. Resolve transcript locations from a trusted host binding, not a caller-supplied local path. |
| `watch` | The same files expose `agentSession.subscribe` and `nativeChat.subscribe`. | Bind opaque native cursors to the actual session/generation and journal epoch. Preserve replacement frames and native ordering; keep ACS cursors independent. |
| `state`, receiver `observe` | `structured-agent-session-status-stream.ts`: `agentSession.subscribeStatus`; `structured-agent-session-current-requests.ts`: `currentRequests`; options reads and host `readStatusSummary`. | Retain unknown/freshness semantics and current child ownership. The public plugin status projection does not prove a complete Native binding. |
| `act` | `structured-agent-session.ts`, `structured-agent-session-prompt-response.ts`, `structured-agent-session-queued-methods.ts`: send/cancel, approval/question responses, queued update/delete/resume, `setOption`, `conversationCommand(clear/compact)`. | Use existing host controllers and their operation receipts/CAS checks. Background-task stop uses `agentSession.cancel` with `scope: "background-tasks"` and the exact `taskId`. Resolve subagent targets explicitly; do not substitute stop-all. Queue resume, interrupted-turn continuation and restart continuation are distinct operations. |
| `readResource` | `structured-agent-session-item.ts`: `agentSession.item`; `structured-agent-session-visual.ts`: `readVisual`; attachment reads; `files.ts`: `files.read/readChunk` for workspace files. | Resolve opaque resource references to the owning host/session and preserve existing byte bounds. `readVisual` explicitly restricts supported locations. Native tool blocks retain their existing diff data; `files.openDiff` opens a view rather than supplying a general diff-read payload. |
| `prepareAttachment` | `structured-agent-session-attachments.ts`: `agentSessionAttachment.uploadStart`, `uploadAppend`, `uploadCommit`, `uploadAbort`, `read`, `readTextChunk`. | Transfer verified bytes to the actual destination host and return its committed native attachment reference. Never reuse an ACS-local filesystem path as a remote native path. |
| `reveal` | `structured-agent-session-reveal.ts`: `agentSession.reveal`; public `workspace.open` / `editor.open`; internal `files.openDiff` and terminal reveal where authorized. | Use host-owned session location and current navigation permission. Do not redirect from caller-provided workspace identity. |
| Receiver `admit` / `reconcile` | `src/main/native-chat/agent-session-wire/structured-agent-session-host.ts`: `send`, `sendAnswer`, `waitForSendSettlement`; `structured-agent-session-command-admission.ts`: command receipts. | Verify the sealed Core command and exact current binding. Reconcile the original operation without resubmission or a replacement session. Journal acceptance alone is not Native ACK. |

## Admission and generation gap

`src/shared/agent-session/lifecycle/agent-session-mutation-envelope.ts`, in `admitAgentSessionMutation`, explicitly ignores `expectedRuntimeFence`. Conversation writes can be accepted independently of the provider writer lease. Mapping ACS `provider_generation` to that field therefore does not enforce the original target generation.

The actual admission seam is `beginStructuredAgentSessionInputHandover` in `src/main/native-chat/agent-session-wire/structured-agent-session-input-handover.ts`: `serialize(sessionId)` performs readiness validation, prepares the input, validates again, then calls synchronous enqueue. `structured-agent-session-input-readiness.ts` checks the current session object, exact child binding, pending submission, child readiness, stopping state and applicable holds. The bridge needs its exact host/session/generation check inside this host ordering. A sent enqueue remains a sent fact even when its waiting caller is subsequently cancelled.

`structured-agent-session-send-compatibility.ts` can return successful journal acceptance while dispatch is still pending. Native admission outcomes must follow actual settlement/receipt evidence; do not turn `ok: true` into `accepted` or manufacture an ACK. Emit `SourceLink` only from the original handoff plus the actual matching host receipt/input reference. Content similarity, timestamps and final assistant prose do not establish this association or an ACS explicit reply.

## Public API and authorization boundary

`resources/plugins/types/orca-host.d.ts` declares Host API **1.4**. `orca-worker.d.ts` exposes default worker activation, command registration, panel handlers, hooks and event subscriptions. The method registry is `src/shared/plugins/workers/plugin-host-api.ts`, with workspace actions in `plugin-host-api-workspace-methods.ts`. It contains no complete Native transcript/provider-registration interface. Public events in `src/shared/plugins/events/plugin-events.ts` are workspace lifecycle/focus and bounded `agent.status.changed` projections.

Public calls retain approved capabilities, allowed surfaces and revocation checks through `plugin-host-call-adapter.ts`, `plugin-host-methods.ts` and `PluginHostCallScope.assertActive`; workspace bindings pass a further `beforeEffect` check. These permissions do not confer blanket Native transcript access or all-workspace authority on an ACS caller.

The internal RPC routes above generally require `permission: "workspace"`, which `src/main/runtime/rpc/rpc-method-permission.ts` defines as host-user-equivalent authority. `rpc-request-admission-prologue.ts` applies the authenticated caller scope; `structured-agent-session-gate.ts` additionally gates the supported structured-session audience and derives caller keys. Neither an ACS bearer nor management role can substitute for actual host authorization.

The smallest host extension is a session-scoped facade over these existing controllers, with explicit per-operation host grants, current-generation checks, bounded native data and original-operation reconciliation. Unprovided operations return typed `host_extension_required` / `unsupported`. Existing Native blocks, tool results, diffs, questions, approvals, children, background tasks, model/effort controls and history remain owned by Orca; no UI migration or Orca business-source change is implied by this report.

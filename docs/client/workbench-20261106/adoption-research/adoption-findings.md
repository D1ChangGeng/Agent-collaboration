# Orca / T3 source adoption research — 2026-11-06

Scope: fixed-source acquisition and contract analysis. App installation, build, model execution and real cross-host behavior were not exercised. Visual and temporal observations have separate evidence notes.

## Findings that change the decision

1. **Orca is an official, complete open-source App candidate.** onorca.dev's View on GitHub points to stablyai/orca, whose root contains desktop src, native, mobile, cloud relay, plugins/examples and build tooling. Root LICENSE is MIT, copyright 2026 Lovecast Inc. T3 is also MIT, copyright 2026 T3 Tools Inc. Retain the applicable notices and check included third-party licenses/assets for the selected distribution scope.
2. **Preserving Orca whole is a credible adoption direction.** This is a stronger route than treating it as a screenshot to rebuild. Existing agent launch, native chat, terminal/PTY, workspace/worktree, browser, file/editor, SSH, runtime, session restoration and orchestration implementations should remain the starting responsibility owners. Their actual integrated performance and platform behavior are not established by this source-only inquiry.
3. **The plugin contract does not currently let a plugin replace or extend the main left navigation as arbitrary Project/Route groups.** It supports panels, commands, events, hooks, language packs, keybindings, VM recipes, appearance themes, syntax, custom editors, new files, settings, status bar items. The panel schema explicitly places its icon in the **right-sidebar activity bar**. `sidebarCards`, `agentHarnesses`, `skills`, `mcpServers`, `taskSources`, `connections` are explicitly reserved; schema requires their arrays to be empty. A right panel can render ACS organization and drive some existing actions. This restriction concerns custom plugin contributions. Stock Orca already has ProjectGroup hierarchy, folder workspaces and nested workspaces; test those before deciding that a specialized, authority-synchronized left tree needs source changes.
4. **Orca already has substantive durable coordination.** It must not be described as a GUI without persistent messages or remote agents. The inspected code defines durable Run/Task/Dispatch, question-answer relationships, typed messages, ordered inbox reads, consumer-generation fencing, mutation receipts, worker start/control/stop/release, and federation dispatch/relay state. Its overlap with ACS's personal multi-host collaboration use case is high. Whether it fully replaces the user's ACS workflow requires a concrete acceptance task, not invented ACS-exclusive claims.

## Source baselines

| Item | Orca | T3 |
|---|---|---|
| Official repo | https://github.com/stablyai/orca | https://github.com/pingdotgg/t3code |
| Inspected default HEAD | 9055eb9344dac1300311337cb1f0040d8094e3c2 | 938b4d45255fa92c11a03e0a5e946b2e438aabb3 |
| Commit time UTC | 2026-11-05T21:24:09Z | 2026-11-05T21:15:00Z |
| Root license | https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/LICENSE | https://github.com/pingdotgg/t3code/blob/938b4d45255fa92c11a03e0a5e946b2e438aabb3/LICENSE |
| Platform description | Desktop macOS/Windows/Linux, mobile companion, remote runtime (README) | Electron desktop, web client and iOS/Android; execution hosted by server (README/architecture) |
| Codebase | Electron main/preload/renderer, native runtime, Node server/CLI, mobile, cloud | Apps/server/web/desktop/mobile; shared contracts and client-runtime; provider packages |
| Evidence | License, package, schemas, representative runtime source read | License, README, architecture, adding-provider, outside-agents docs read |

The API returned those commits as main during this inquiry; it does not guarantee main will remain unchanged. No second checkout was modified. The previously inspected T3 a21d788 baseline should not be mixed with this latest snapshot.

## What the actual Orca source says

- `src/main/runtime/orchestration/types.ts`: Run binds coordinator pane/Orca session plus consumer generation; Dispatch is an attempt identity, has retry/follow-up links, assignee session/handle/pane and lifecycle; Message has run id, sender/recipient, thread id, sequence, delivery contract/read/delivered state. Question stores answer message/body/generation.
- `src/shared/orca-session-address.ts`: structured sessions use an Orca-minted durable id, independent of provider id; after clear, orchestration stores lineage-root ids. PTYs have no Orca session id today; terminal handle and pane cannot be casually conflated with durable agent identity.
- `orchestration-caller-identity.ts`, `runs/run-scope.ts`: structured callers come from dispatch-resolved session context; pane/session evidence binds a Run. Caller binding is not merely a user-supplied display name.
- `messaging/send-methods.ts`: resolves actual sender, recipient and Run; checks lifecycle authority; handles run/dispatch/session/group routing, mutation replay, federated mail and settled-worker follow-ups.
- `messaging/check-methods.ts`: consuming inbox checks resolve current caller, fence another pane's dispatch, distinguish peek/history and consuming reads, and withdraw stale queued chat mail.
- `db/messages/message-inbox.ts`: unread messages select current-delivery rows ordered by sequence; explicit read differs from delivered push; supports thread-addressed replies.
- `db/messages/mailbox-consumer.ts`: validates consumer generation inside the delivery transaction, throwing consumer_fenced after replacement.
- `worker/workers.ts`: RPC `orchestration.workerStart`; resolves caller, Run authority, task/spec and worker start plan. It is an implementation entry, not only a marketing command.
- `runtime-orchestration-federation.ts` and federation/attachment rows: remote orchestration mutation envelopes, capability/contract verification, sync/ack progress, runtime epoch and peer fingerprint are represented. Actual cross-host runtime interoperability was not exercised here.

These observations establish real implementation contracts, not an end-to-end correctness audit. No basis was found to dismiss Orca identity as session-only or its messages as ephemeral; some current contracts explicitly preserve lineage and fence stale consumers. ACS stable AgentSlot and Orca Run/Dispatch/Orca session are different named models, but difference in naming is not evidence of a missing user capability. Inspect mappings and real resume/reassign/reply tasks before deciding replacement or coexistence.

## Extension and acquisition matrix

| Route | Established capability | Practical implication / open boundary |
|---|---|---|
| Full Orca fork | Complete public App + MIT + build tooling | Preserve whole workbench; add narrow Project/Route organization and adapter seam. Native build/distribution and third-party obligations require separate validation. |
| Orca panel plugin | HTML or components UI; right sidebar; own storage/settings/secrets; panel ↔ worker request/post | Good bounded ACS overview/projection trial, not full left navigation integration. |
| Orca trusted worker | Separate Node process; host calls checked against approved capabilities; ordinary Node imports | Can technically host an ACS HTTP/client adapter. Actual ACS auth/session binding and network calls were not implemented or verified. Plugin worker is application extension capacity, not automatically an AI agent identity. |
| Plugin host API 1.4 | workspace.list/open; terminal.create/read/send; agent.launch; editor.open; events; commands | Can discover existing Orca workspaces on hosts and open them. No inspected method supplies arbitrary workspace metadata writes or Project/Route schema registration. Private plugin storage can hold mappings, with ownership explicitly defined. |
| MCP in launched harness | Existing harness configuration may supply external MCP | Do not claim an implemented plugin `mcpServers` contribution: it is reserved. Source-level/provider configuration should be checked for each harness. |
| Orca CLI/RPC | Real send/check/ask/workerStart lifecycle and federation | ACS may bridge as external service, but neither ACK nor a Run/Dispatch mirror should silently become a second authority. |
| T3 fork/provider driver | Provider package and normalized command/event contracts; builtInDrivers/client registry/model manifest registration documented | Genuine source integration path for custom harness, requiring implementation and replay tests. Not a claim of a drop-in generic plugin installer. |
| T3 outside-agent MCP | Environment /mcp with HTTP+OAuth; read-only or permission-capped mutation access; start/send/stop threads; revocable approved clients | T3 already provides outside-agent control and persisted execution. ACS can orchestrate T3 via this MCP or CLI, if identity/auth and result handling are mapped. Different from T3 UI consuming arbitrary remote MCP directly. |

T3 architecture states server owns workspace, providers, terminals, Git/files; shared client-runtime owns connection/domain state. Orchestration commits events, persisted projections, command receipt and outbox in one transaction; effect worker performs I/O afterward. Projections remain authoritative after event pruning. This is substantial execution state to preserve if adopting T3; drawing a new sidebar does not integrate it automatically.

## Why Project/Route UI alone may not finish integration

If Orca replaces ACS for this workflow, first map existing user tasks into Orca-native objects and test that contract; avoid adding redundant ACS mirrors only to preserve old names.

If ACS remains authoritative for Project/Route/AgentSlot or messages, a narrow adapter still must define:
- Project/Route registry → Orca host-qualified project/workspace mapping; do not equate Route with git worktree automatically.
- AgentSlot → Orca durable session/dispatch/terminal execution binding, including replacement, clear/resume and stale consumers.
- One owner for message id, reply relation, delivery/read/ack, retries and history. Separate UI projection from delivery custody.
- One owner for start/stop/retry and readiness; concurrent ACS invoke and Orca workerStart could otherwise create duplicate execution.
- Cross-host auth, caller identity, capabilities and authoritative error/result boundary.
- Disconnected/restarted client behavior and persistence, with actual task evidence.

The double-fact risk is architectural: both products already persist object/state/message lifecycles. Merely renaming sidebar groups cannot make their task, identity or mailbox states coherent.

## Adoption trial and verification scope

The files are under commit-qualified `orca/<sha>/...` and `t3/<sha>/...`; source-manifest.json lists every acquired original. First validate the complete user task in stock Orca, including its existing grouping and coordination. The observed gap determines whether a small organization extension or an ACS adapter is useful. Concrete product direction and UI acceptance remain subject to user review.


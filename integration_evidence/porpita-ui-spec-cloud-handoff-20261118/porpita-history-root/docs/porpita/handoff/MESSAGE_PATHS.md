# Porpita communication path map

This maps the original fourteen entry points to product code. Test and installer outcomes are tracked separately.

| Path | Entry and owning implementation |
| --- | --- |
| MP01 | Native MCP: `src/main/porpita/native-communication.ts` and `native-agent-registration.ts` bind the actual session and its Agent credential. Codex and OpenCode receive their process-scoped ACS configuration. Core owns send, reply_to and wait. |
| MP02 | `src/main/runtime/rpc/methods/orchestration/messaging/send-methods.ts` and `send-resolved-point.ts` resolve the attested caller and target. `src/main/porpita/legacy-send.ts` uses the original ACS send key and returns the Core handle. |
| MP03 | `messaging/ask-methods.ts`, `ask-remote.ts`, `reply-method.ts` and `src/main/porpita/legacy-question*.ts` use the original Core question and explicit reply_to. Host stores question state and references. |
| MP04 | `src/main/porpita/legacy-read.ts` reads Core history; `legacy-consumer.ts` maintains the separate workflow consumer frontier. |
| MP05 | `src/main/porpita/legacy-group.ts` captures the original audience, sends individually and retains per-member receipts through a partial failure. |
| MP06 | `src/main/porpita/legacy-lifecycle.ts` validates the current Dispatch, sends the ACS notice and settles the Host workflow. Remote `messaging/send-remote.ts` sends the report over ACS and relays its exact handle with authorized lifecycle facts to the Run home. `federation-acs-workflow.ts` applies those facts without importing a mailbox row. |
| MP07 | `src/main/porpita/native-host-bridge.ts` and `native-receiver-input.ts` bind the original Core handover to the execution Host. The Host admission queue owns accepted input; ordinary chat/tool/approval state stays native. |
| MP08 | A paired runtime continues to serve its workspaces and process control. The receiving Host prepares its real Native Chat in `federation/federation.ts`; the Home sends via `src/main/porpita/worker-instruction.ts`. The same ACS authority/incarnation/project and the recorded Agent contact route the instruction, control, question and report. `federation/federation-relay.ts` refuses legacy body imports. |
| MP09 | `src/main/porpita/terminal-agent-message.ts` handles automated Agent recipients through ACS. Actual human terminal use and normal shell input use the existing terminal controller. |
| MP10 | `src/main/runtime/rpc/methods/collaboration/` and `src/main/porpita/human-send.ts` supply the user Client composer, reply and file upload. Read, drafts and preferences use the current Core Client scope. |
| MP11 | The inherited `src/main/native-chat/agent-session-wire/` owns user sends, queue, stop and steer; the normal composer remains attached to the existing Native Chat. |
| MP12 | The native journal, provider adapters and original tool/approval panels retain execution output and user authority; collaboration records can point to original Native input. |
| MP13 | `src/main/porpita/legacy-history-archive.ts` reads explicit Orca history copies and `legacy-profile-import.ts` copies workspace and readable Native index data into an independent profile. Historical authors and IDs are retained; historical operations are not dispatched. |
| MP14 | `src/cli/` and the shipped Porpita skills use the same public runtime calls as the app. Worker instruction and lifecycle RPCs route through the above adapters; typed Host workflow state stays in the original store. |

The Host/RPC compatibility aliases and database format names stay available to existing tooling. Porpita speaks ACS for new collaboration traffic. The archived Orca mailbox is an explicit historical read.


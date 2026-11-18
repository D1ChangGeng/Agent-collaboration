# 源码与事实索引

ACS参考 `e5d71968a13e67e3dc51e318867d4ed9a1f946ac`；Orca参考 `26179069b664b2fc172963564ed419d97892b6c9`。以下是开发定位依据，不是已完成Porpita接入的证明。

| ID | 来源 | 本次观察范围 | 实施意义 |
|---|---|---|---|
| S01 | [branches/main](https://api.github.com/repos/D1ChangGeng/Agent-collaboration/branches/main) | observed_ref | main resolves to e5d71968 on package preparation |
| S02 | [branches/main](https://api.github.com/repos/stablyai/orca/branches/main) | observed_ref | main resolves to 26179069 on package preparation |
| S03 | [package.json](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/package.json) | reviewed_excerpt | version 1.4.214; desktop/build:win and test:e2e scripts |
| S04 | [config/electron-builder.config.cjs](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/config/electron-builder.config.cjs) | reviewed_excerpt | brand identity, release channels, packaged native/daemon assets |
| S05 | [src/main/runtime/rpc/methods/orchestration/messaging/send-methods.ts](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/main/runtime/rpc/methods/orchestration/messaging/send-methods.ts) | reviewed_excerpt | actual sender/routing and run/dispatch/report paths |
| S06 | [src/main/native-chat/agent-session-wire/delivery/structured-agent-session-input-handover.ts](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/main/native-chat/agent-session-wire/delivery/structured-agent-session-input-handover.ts) | reviewed_excerpt | serialized prepare/validate/enqueue seam |
| S07 | [src/shared/agent-session/lifecycle/agent-session-mutation-envelope.ts](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/shared/agent-session/lifecycle/agent-session-mutation-envelope.ts) | reviewed_excerpt | ordinary mutations ignore expectedRuntimeFence |
| S08 | [docs/reference/plugin-host-api.md](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/docs/reference/plugin-host-api.md) | reviewed_excerpt | Host API 1.4 methods; not a full ACS atomic receiver contract |
| S09 | [docs/site/content/docs/cli/orchestration.mdx](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/docs/site/content/docs/cli/orchestration.mdx) | reviewed_excerpt | normal/task messages, groups, ask/reply/check/gate semantics |
| S10 | [src/renderer/src/components/native-chat/NativeChatView.tsx](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/renderer/src/components/native-chat/NativeChatView.tsx) | located_search | native chat renderer reuse entry; inspect implementation when editing |
| S11 | [src/renderer/src/components/native-chat/pane/actions/NativeChatPaneHeader.tsx](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/renderer/src/components/native-chat/pane/actions/NativeChatPaneHeader.tsx) | located_search | header/menu minimal extensions |
| S12 | [src/renderer/src/components/native-chat/pane/actions/NativeChatPaneMenuItems.tsx](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/renderer/src/components/native-chat/pane/actions/NativeChatPaneMenuItems.tsx) | located_search | pane actions |
| S13 | [src/renderer/src/components/native-chat/attachments/intake/NativeChatPaneFileDropSurface.tsx](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/src/renderer/src/components/native-chat/attachments/intake/NativeChatPaneFileDropSurface.tsx) | located_search | native attachment intake |
| S14 | [sdk/orca-receiver-port.ts](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/orca-receiver-port.ts) | reviewed_excerpt | existing 4-operation port and actual Host callback needs |
| S15 | [docs/runtime/COMMUNICATION-CLIENT-API.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/docs/runtime/COMMUNICATION-CLIENT-API.md) | reviewed_excerpt | adoption flags, client API, actual search/personal state semantics |
| S16 | [sdk/ORCA-RECEIVER-INTEGRATION.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/ORCA-RECEIVER-INTEGRATION.md) | prior_audit_at_same_acs_ref | existing Python backend/router; actual Host not installed in prior audit |
| S17 | [runtime/orca_receiver_backend.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/runtime/orca_receiver_backend.py) | prior_audit_at_same_acs_ref | reuse signed verifier/prepared/original dispatch storage |
| S18 | [sdk/communication-client.ts](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/communication-client.ts) | prior_audit_at_same_acs_ref | adopt existing HTTP client; do not re-specify wire |
| S19 | [sdk/communication-state.ts](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/communication-state.ts) | prior_audit_at_same_acs_ref | reuse local SDK state and owner changes |
| S20 | [sdk/communication-stream.ts](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/communication-stream.ts) | prior_audit_at_same_acs_ref | SSE client |
| S21 | [sdk/integration-ports.ts](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/sdk/integration-ports.ts) | prior_audit_at_same_acs_ref | Native/Workspace/management delegates |
| S22 | [runtime/client_models.schema.json](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/runtime/client_models.schema.json) | prior_audit_at_same_acs_ref | adopted source of DTOs |
| S23 | [LICENSE](https://github.com/stablyai/orca/blob/26179069b664b2fc172963564ed419d97892b6c9/LICENSE) | reviewed_full | MIT; retain notices |
| S24 | [LICENSE](https://github.com/D1ChangGeng/Agent-collaboration/blob/e5d71968a13e67e3dc51e318867d4ed9a1f946ac/LICENSE) | reviewed_excerpt | Sustainable Use License 1.0; preserve distinct licensing |
| S25 | [native Chat surfaces and supported interactions; website may evolve independently of pin](https://www.onorca.dev/docs/agents/native-chat) | official_docs_observed_not_installed_app | native Chat surfaces and supported interactions; website may evolve independently of pin |
| S26 | [2025-06-23; Zooid arrangement and colony growth in Porpita porpita; DOI 10.1186/s12983-025-00565-3; name rationale only](https://pubmed.ncbi.nlm.nih.gov/40551163/) | primary_paper_abstract_checked | 2025-06-23; Zooid arrangement and colony growth in Porpita porpita; DOI 10.1186/s12983-025-00565-3; name rationale only |
| S27 | `references/PRIOR_AUDIT_CONTEXT.md` | provided_prior_audit | historical audit known CI/qualification limits; not a mandate to repeat all defensive work |

## 实施时需要查找的未核查路径

branding/userData/protocol/update/telemetry的所有消费者、renderer主导航/状态store、具体ask/reply/check/group/report/wake/federation实现、各Harness MCP注入和native attachment实现。WP00按当前checkout符号定位，再在实际改动点阅读即可；不是要求先全面研究整个上游仓库。

`located_search`仅证明文件位置与片段；`reviewed_excerpt`不表示完整文件审计；`prior_audit_at_same_acs_ref`来自本对话已给审计，不能被宣传为新的运行测试。

文档提出的Porpita模块名、进程名和schema是目标/实施默认，不是上游公开API。直接使用已存在的等效实现，不以文件名字不一样判断缺功能。

# 来源索引与证据边界

本包不附带上游源码。固定 commit 的 source_read 是本次实际读取；implementation_check 是实现时需要定位/重读的源码线索，不能被当成已验证功能。旧对话中对测试和 PR 的结论不自动外推到本基线。

## A01 · source_read

[pyproject.toml](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/pyproject.toml)

读取范围：1-end。包版本与 Python/依赖/entry 基线；不是生产运行版本证明。

## A02 · source_read

[docs/runtime/COMMUNICATION.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/docs/runtime/COMMUNICATION.md)

读取范围：1-197。自然消息、可信身份、Root namespace、原子提交、wait/notice/Native 边界。

## A03 · source_read

[docs/runtime/COMMUNICATION-STATUS.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/docs/runtime/COMMUNICATION-STATUS.md)

读取范围：1-107。已声明证据层次、主链与支持限制；本包未重新执行这些证据。

## A04 · implementation_check

[docs/runtime/ROOT-MANAGEMENT.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/docs/runtime/ROOT-MANAGEMENT.md)

读取范围：re-read current full file。历史对话已读；本包执行时重验当前配置/权限调用链。

## A05 · implementation_check

[runtime/communication.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime/communication.py)

读取范围：full call graph。既有消息权威入口，必须复用。

## A06 · implementation_check

[runtime/native_delivery.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime/native_delivery.py)

读取范围：full call graph。最小 Native 发起，旧路径回归。

## A07 · implementation_check

[runtime/communication_dispatch.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime/communication_dispatch.py)

读取范围：full call graph。Outbox/维护器/默认并发与 fence。

## A08 · implementation_check

[runtime/codex_driver.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime/codex_driver.py)

读取范围：protocol entrypoints。目录已见；实际原生版本/receipt 由 Codex 核对。

## A09 · implementation_check

[runtime/opencode_driver.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime/opencode_driver.py)

读取范围：locate via git ls-files。现有 OpenCode Driver 定位线索。

## A10 · implementation_check

[runtime_deployment/receiver_authority.py](https://github.com/D1ChangGeng/Agent-collaboration/blob/19d7881d49ee887315c54c5bc02e0cc424061376/runtime_deployment/receiver_authority.py)

读取范围：full call graph。接收端 Node/发送方验证线索。

## O01 · source_read

[src/shared/native-chat/native-chat-types.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/shared/native-chat/native-chat-types.ts)

读取范围：1-240。NativeChatMessage/Block/source/linkage，原生执行数据不属 ACS。

## O02 · source_read

[docs/reference/plugin-host-api.md](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/docs/reference/plugin-host-api.md)

读取范围：1-45。Host API 1.4 公共方法/权限/surface；不证明通信引擎可替换。

## O03 · source_read

[src/main/native-chat/agent-session-wire/structured-agent-session-input-readiness.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/native-chat/agent-session-wire/structured-agent-session-input-readiness.ts)

读取范围：full。当前 child/ready/stopping/command/prompt 再准入检查。

## O04 · implementation_check

[src/main/runtime/orchestration/mailbox-notification-coordinator.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/mailbox-notification-coordinator.ts)

读取范围：full + tests。waiter 与 native 提醒协调；历史已读，固定提交需重验。

## O05 · implementation_check

[src/main/runtime/orchestration/mailbox-pointer-delivery.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/mailbox-pointer-delivery.ts)

读取范围：stage/submit/resume + tests。terminal 输入与未知回车副作用。

## O06 · implementation_check

[src/main/runtime/orchestration/structured-mailbox-pointer-delivery.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/structured-mailbox-pointer-delivery.ts)

读取范围：full + tests。结构化队列和原操作核对，不复制 dispatch 生存期。

## O07 · implementation_check

[src/main/runtime/orchestration/structured-mail-custody.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/structured-mail-custody.ts)

读取范围：full + tests。消息接管与输入待处理证据。

## O08 · implementation_check

[src/main/runtime/agent-state-rules/agent-state-rules-schema.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/agent-state-rules/agent-state-rules-schema.ts)

读取范围：rules and hook callers。多来源状态、强弱推断。

## O09 · implementation_check

[src/main/runtime/orchestration/federation-sync-capability.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/federation-sync-capability.ts)

读取范围：relay family + tests。对端能力缓存与代次失效。

## O10 · implementation_check

[src/main/runtime/orchestration/db/federation/federation-relay-enqueue.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/orchestration/db/federation/federation-relay-enqueue.ts)

读取范围：enqueue/ack/import。有界 relay、sequence 与 ACK。

## O11 · implementation_check

[src/main/runtime/rpc/methods/orchestration/messaging/send-point-to-point.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/main/runtime/rpc/methods/orchestration/messaging/send-point-to-point.ts)

读取范围：full + lifecycle callers。普通消息与任务状态耦合点，只提取通信机制。

## O12 · implementation_check

[src/renderer/src/components/native-chat/NativeChatStructuredSession.tsx](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/renderer/src/components/native-chat/NativeChatStructuredSession.tsx)

读取范围：renderer hook graph。完整 Chat UI 数据依赖的实施清单。

## O13 · implementation_check

[src/shared/agent-session/agent-session-message-source.ts](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/src/shared/agent-session/agent-session-message-source.ts)

读取范围：source provenance。原生消息来源和 ACS exact linkage 映射。

## O14 · implementation_check

[docs/reference/plugin-manifest.md](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/docs/reference/plugin-manifest.md)

读取范围：capabilities/replaces/hooks。公开插件能力与 host gap 核对。

## O15 · implementation_check

[docs/reference/plugin-authoring.md](https://github.com/stablyai/orca/blob/53fbfded41b8b0462d7ccd029475f89d12aa9bf5/docs/reference/plugin-authoring.md)

读取范围：workers/requests/security。worker/Panel 通道，不能以 action replacement 替换 core。

## 官方产品参考

[Orca Native Chat](https://www.onorca.dev/docs/agents/native-chat)（2026-11-06 查阅）。仅补充界面现有能力清单，不以网站“支持某 Agent”代替 Adapter 资格。

## 不宣称的事实

本轮没有修改业务仓库、运行真实 Harness、执行生产迁移、验收 Orca 插件或测量性能。包内案例是测试规格/合成夹具。任何 API、状态字段、表结构或 endpoint 新设计均为目标规范，不是声称当前 ACS 已实现。

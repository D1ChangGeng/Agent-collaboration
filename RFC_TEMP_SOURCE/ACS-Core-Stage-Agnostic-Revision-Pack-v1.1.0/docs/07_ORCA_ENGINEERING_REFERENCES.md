# 07｜Orca 实现吸收：已知路径、设计意图及禁止越界

以 `stablyai/orca` 的参考快照 `53fbfded41b8b0462d7ccd029475f89d12aa9bf5` 作为源码导航；实施以 Codex 实际所见版本为准。不开展独立研究阶段，直接在对应 P0/P1 代码修改时阅读。未经阅读实际代码的性质不是“已实现事实”。

| Orca 线索路径 | 已见工程思想 | ACS 应吸收 | 禁止照搬 |
|---|---|---|---|
| `src/main/runtime/orchestration/mailbox-notification-coordinator.ts` | 路由等待者、通知与接收机制的竞合 | 安全唤醒、与活动 wait 合并 | Coordinator/Run 的业务所有权 |
| `src/main/runtime/orchestration/mailbox-pointer-delivery.ts` | 针对 terminal 的指针式消息交接与 Enter/输入状态处理 | 交接后状态检查、未知副作用恢复 | 假定可直接控制任意外部 PTY |
| `src/main/runtime/orchestration/structured-mailbox-pointer-delivery.ts` | 结构化 Chat 与终端输入路径不同、操作 custody 核对 | Native operation 查询/去重域证据 | Orca 原生 Chat 视为 ACS 事实数据库 |
| `src/main/native-chat/agent-session-wire/structured-agent-session-input-readiness.ts` | handoff 前的原生就绪校验与人工输入保护 | 最后准入、审批/用户草稿等待 | 把特定 Provider 的 UI 事件当跨 Harness 保证 |
| `src/main/runtime/orchestration/terminal-authority/*` | 将可发言/可处理消息的身份与运行实例关联 | 可信实例/代次/权限关系 | 让 Dispatch 成为 ACS 发信前提 |
| `src/main/runtime/orchestration/federation-*.ts` 和 `db/federation/*` | 远端 Relay 的消息/能力/确认状态 | peer capability、混合版本、断线对账 | 新建平行 Relay 权威 |
| `src/shared/native-chat/native-chat-types.ts` | 原生执行消息和工具/Diff/审批多源表示 | UI Host delegation 与 provenance | ACS 复制 Native transcript 数据与执行状态 |
| `docs/reference/plugin-host-api.md` | 插件能力受用户授权且 API 显式限定 | Host gap 和最小 Receiver 端口 | 预设公开 API 能替换 Orchestration |

与 ACS 对应应直接定位：`runtime/communication.py`、`communication_dispatch.py`、`communication_management.py`、`native_delivery.py`、`runtime_deployment/receiver_codex.py`、`receiver_opencode.py`、`runtime/codex_driver.py`、`runtime/communication_core_schema.sql` 及 Node/Receiver 相关模块。文件名为参考快照路径，实际模块若有重构先按调用链查找而不是创建同名文件。

## 吸收判据

对每项机制回答并记入 `handoff/DECISION_LOG_TEMPLATE.md`：

1. ACS 当前是否已有等价可验证能力？已有则只做必要安全/覆盖缺口；
2. Orca 的机制属于通用通信正确性、Host-specific 输入优化，还是 Task/Dispatch 业务逻辑？只提取前两类；
3. 是否要求 Orca 才可使用？P0 Core 不接受此依赖；P1 Host port 可要求具体 Host 能力；
4. 哪项真实观察证明 `supported`，哪项只能 `inferred`，无能力时如何降级？
5. 代码增量、迁移、正/反/故障测试是否都可明确定位？

禁止将 Orca 仓库克隆到 ACS 产品源目录内，禁止未经相应许可审查直接复制代码。可参考实现思想；任何代码移植必须保留来源和许可证责任。

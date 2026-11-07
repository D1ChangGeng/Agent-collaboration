# 03｜P0 必交：跨 Harness 通信运行时增强

本章是**可执行的行为规范**。允许 Codex 根据当前真实源码选取最小实现，字段名称只作为映射语义；旧 ACS 的正确机制不应重新实现。

## P0-01 已有接口与正确性不回归

保留 `read_profile`、`list_collaborators`、`send_message`、`check_inbox`、`list_messages`、`read_message`、`wait_for_response`、`list_harnesses` 的身份、默认值、权限与返回语义；`configure_root` 的单一 Root 入口及 Client/Root/Route 责任边界不变。正常消息不用创建 Task/Run/Dispatch/Gate。对同文不同 request key、同键异文、第三方 reply、message_only+sync、等待超时晚到回复、UTF-8 续读建立正反例。

## P0-02 Adapter 能力与证据

新/现有 Adapter 至少可提供：`describe(binding)`（支持的操作与证据范围）；`observe(binding)`（多维当前状态及 freshness）；`admit_input(sealed_operation)`（最终受权交接，结果可能 accepted/queued/definitively_not_admitted/unknown）；`reconcile(operation_id, original_binding)`（查询同一 Native 操作的原始去重域）。无实现时返回 typed `unsupported`，不可伪造完整能力。可选 `restore/subscribe` 仅在原生支持时启用。先扩展已有 Driver/Receiver 接口，禁止建立“虚假通用 Driver”让所有 Harness 具有同样控制能力。

建议状态维度：connection、process、native_session、input_readiness、blocker、version/evidence_age；`unknown ≠ idle`。Hook/PTY heuristic 只在可信来源/绑定代次下参与判断，不能单凭安静或标题决定模型已消费输入。能力缓存绑定实际 executable/version/config/account/host/connection epoch，变化需失效。

## P0-03 Native 最后准入

每一次可能产生 Native 副作用的动作必须具备现有 Authority/Receiver 允许的 operation identity、message reference、不可伪造封存内容、实际接收目标与授权证据；在准备前和 Provider handoff 前重验。busy 可在支持安全原生排队且记录 queued 的情况下交付，否则继续 deferred；approval/question/用户输入草稿默认不自动穿透。即使 adapter 宣称 `supported`，当前可用性仍需检查。单 Slot 绑定多 receiver 歧义时不可广播执行。

## P0-04 未知 ACK、对账和旧代次隔离

如果请求可能已经送至 Provider，但网络/进程/ACK 中断，则 `outcome=unknown`。只允许对**相同** operation 和原生去重域执行 reconcile 或已证明 replay-safe 的重放；否则必须保留未知而不再次启动 Native 回合。旧 Epoch/Session/Process receipt 属历史事实，不能完成新绑定操作。原生 consumed/turn completed 不等于有效显式 reply。沿用现有 operation ledger、Outbox、Node Journal、receiver fence；只有证明旧结构无处记录时增列/表。

## P0-05 消息唤醒与连续性

收件箱持久消息不因 UI 关闭或 Session 退出而删除。让 Runtime 依据已认证/可新鲜观察的 readiness 推进 due 消息，不要求 Agent 无限轮询；通知是 hint，不是消费证据；消息实体不能因通知去重被折叠。活动 wait 正确收到显式 reply 时不需要重复启动其他 Native 回合。已失效 wait lease 应有界清理且不影响消息。原生 resume 仅对经验证可恢复的 Session 执行；新 Session 配置要有明确管理授权，不能凭名称自行重新找个 Agent 代收。

## P0-06 跨机器与诊断

Node/Receiver/Tunnel 继续采用 ACS 当前受信网络。远端可声明自己的能力/代次；混合版本不得默默吞掉新字段或假 ACK。必要时增加小型只读诊断：消息已接受 / inbox commit / native dispatch attempted / native ACK/unknown / explicit reply received；每项含来自何处的证据、目标版本、实际阻塞原因和下一条受权动作建议。不得在通知日志暴露私信正文、凭据或其他 Project 流量。

## 最低测试与资格

对已有已安装 Codex/OpenCode 链至少各跑一条真实协议接收与独立发送/关联回复回归；对 busy/approval/draft、native ACK lost、session rebind、receiver epoch、网络断开/恢复以受控故障构造正反例。受控 double 不能替代真实 Native 资格。真实版本未可用时隔离 `blocked` 并继续工作，不能声称通用全 Harness 覆盖。

**P0 退出**：所有 P0 test IDs 在真实适用范围内通过或有明确不可取得环境的资格阻塞；未变代码可保留已有带源版本证据，但当代码/运行版本已变化必须重跑相应回归；不能把 P1/P2 未完成作为 P0 失败理由。

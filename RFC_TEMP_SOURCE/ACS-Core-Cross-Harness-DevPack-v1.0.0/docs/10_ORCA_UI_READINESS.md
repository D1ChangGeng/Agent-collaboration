# 10｜完整 Orca 相关 UI 接入就绪

## 目标不是第二个聊天框

本轮交付完整**后端与集成契约**：让未来客户端能使用 ACS 通信，同时保持 Orca 原生 Chat 的文本/工具调用/结果/Diff/附件/审批/子 Agent/后台任务/模型设置/Session 历史等已有能力。Orca `NativeChatBlock/NativeChatMessage` 明确区分这些原生对象及其来源。[O01] 本包不要求 ACS 复制它们的执行状态或持久 transcript。

客户端层必须可以连接两个 provider：`CommunicationClient`（ACS authority）与 `NativeViewProvider`（Orca/Harness authority）。组合接口见 contracts/orca_integration.ts。面向“通信会话”的 composer 调用 ACS send；面向“原生 Harness 会话”的 composer 保留原 native submit。动作不能因视觉共用输入框而混淆 actor/权限/幂等。

## 必须覆盖的能力族

1. 身份/项目/Route/联系人、稳定地址/显示名/权限动作。
2. 双方通信会话列表、草稿/归档/静音/未读和最新消息摘要。
3. 原文/关联回复/线程投影、分页、定位、检索、长正文继续读取。
4. 发送/等待/状态/错误、离线 pending command、连接恢复与安全重试。
5. Receiver/Host/Harness/Session 的能力、状态证据、未知/过期、错误诊断、恢复入口。
6. system notice、个人 seen、跨设备同步、实时更新/重新快照。
7. 文件/图片的通信附件与原生附件适配；文件位置跨主机不混用。
8. Native 会话联结、原生 transcript/stream、工具卡/结果/Diff/子 Agent/后台任务、审批/问题、停止/恢复、模型/effort/上下文使用量、原生历史及 clear/compact。
9. 原生 workspace/Git/编辑器/浏览器/terminal 定位仍走 Orca；ACS 仅带权限受控引用。

第 8/9 族不是迁入 ACS 领域，而是**保证接入 ACS 后不丢失原生能力**。每项契约由具体 authority delegate；支持不可用时类型化 degraded/unsupported，不构造伪造数据填满 UI。

## 双源消息与回执

ACS message ID 是不可变通信事实；Native row ID 是 Provider journal 事实。ACS 消息被送入 Native 时，记录 exact source linkage (message_handle, operation_id, native_session_ref, native_input_ref?)。同一内容在 transcript 中出现时客户端可以链接/折叠展示，但不能按内容 hash 推测是同一消息，更不能把模型最后一段输出认定为回复。

人类可以在 Native Chat 里观察 Agent 的全部工作，但只有显式 send_message 才产生 ACS 发信；完整 transcript 读取仅经原生 authority 的额外授权。root manager 不因管理关系自动获得下属所有原生推理/工具详情。

## 完整清单与证据

`contracts/ui-feature-matrix.json` 为验收清单，每项包含 id、source、authority、query/command/event、degradation、test IDs。源码已读的结构字段标 source_read；Renderer 对具体字段的接线标 implementation_check，由 Codex 在开发阶段更新到真实文件/符号。

必须实现无 UI headless consumer：握手→一致 snapshot→分页→发信/回复关联→subscription/reconnect→mark_read→附件→状态/恢复→native provider delegation。测试用真实 ACS HTTP/DB，宿主 adapter 的协议层契约测试与真实 Orca 资格分别记录。不能只打印 JSON 或列举 API 后宣称 ready。

## 插件路径和原生路径

公开 Host API 1.4 提供 panels/worker、workspace/agent/terminal 能力，但当前列举方法中没有完整 Native transcript 或 communication provider replacement 接口。[O02] 不能假定 `terminal.sendText` 等价完整可靠投递。优先对公开 API 做适配；缺口的接口、宿主调用链和最小实现位置写入 host-gap-register。

本轮允许构建无 UI bridge/SDK/adapter 实现、测试 provider fake 和宿主扩展设计；不移植 UI、不修改 Orca 业务源码、不偷偷读取内部 DB。对于必须 Fork 才能接入的宿主能力，交付可实现 host-port 合同与测试，标 `host_extension_required`。这不允许把 ACS 自身未实现端点列为宿主缺口。

## 验收标签

每项状态只能为 `implemented_and_verified` / `implemented_host_pending` / `delegated_existing_verified` / `unsupported_by_host` / `blocked`。前三者必须附证据，第四必须有真实源码/能力证明和降级测试；`blocked` 存在时完整 readiness 不通过。宿主范围之外的功能不得算 ACS 缺陷，但已承诺的 ACS 功能也不能靠 delegated 躲避实现。

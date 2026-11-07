# 03｜跨 Harness 通信正确性契约

## 保证分层

G1 安全保证：已成功提交的消息不因 Native Session 退出而丢失；作者及 reply_to 不能伪造；未授权读取/发信/激活被拒绝；未知输入结果不被盲目重发；观察不产生副作用。
G2 条件性活性：在接收端可达、授权持续有效、能力支持、资源最终可用且运行时维护器持续工作时，待投递消息得到推进或明确阻塞结果。没有环境前提时不承诺最终被模型处理。
G3 不保证：语义理解、正确推理、业务完成、永久离线时送达、缺少原生幂等/查询能力时 exactly-once Native execution。不得使用“绝对可靠”覆盖这些限制。

## R-001–R-010：不可变语义

R-001：`sender` 来自可信 ingress context；正文、HTTP 参数、Session 标题均不授予身份。
R-002：保留 Client/Root/Route/ordinary Slot 权限；未绑定不等于 Client；管理者不能默认读取私信。
R-003：to 是稳定授权地址，Native 目标解析只在接收侧完成，默认无需发送方指定 Harness。
R-004：消息提交、reply 索引、请求去重和 Outbox 同一事务；Authority ACK 只能在 commit 后发出。
R-005：幂等键作用域 `(authority_incarnation, tenant, actor_address, operation_kind, client_request_id)`；规范化内容/目标/activation/reply_to/附件摘要不同则冲突；不同键同文是不同消息。
R-006：reply_to 仅引用同一真实对端发给当前作者的请求；第三方委派使用新消息，不能代答。`sync` 与 wait 始终观察同一首个合法显式回复；澄清也是回复。
R-007：Native 接纳、Provider 消费、Native turn 完成、消息在 UI 展示/阅读均不构成显式回复。
R-008：message_only 不 Native 激活，包括与 sync 同时使用时。超时只停止 wait；消息、已触发操作和晚到回复保留。
R-009：读取历史不消费。UTF-8 字节续读保留原 handle 与 next_offset（含 0）；原文和内嵌回复各自预算/游标。
R-010：authority 接受顺序可用于消息/事件游标，但不是跨机器工作发生时间。

## R-011–R-020：接收/恢复

R-011：每次 Native 可能副作用之前持久化 operation_id、message/delivery 引用、canonical hash、binding_epoch、provider_generation、权限校验依据。
R-012：same operation 在 transport retry 使用同 ID；查询与 replay-safe retry 只能作用原 Native 实例/去重域。没有证据不能生成新 operation 来规避未知。
R-013：超时/网络错误/进程退出后 outcome=unknown；reconcile 可返回 accepted/definitively_not_admitted/unknown。只有可验证未接纳或原生同去重域 replay-safe 才允许恢复发送。
R-014：接收端原子检查当前 epoch/generation/operation authority；租约失效不足以阻止旧进程，必须有实际 receiver fence。无法 fence 的通路标低能力，未知时停住。
R-015：准备前和原生 handoff 前重验授权与绑定；撤销在副作用之前阻止执行。已经发往 Provider 的输入不能承诺撤回，记录竞态事实。
R-016：busy 允许安全原生排队或延迟；approval/question/user draft/paused 默认禁止自动穿透；只依据已证明能力和明确策略例外。
R-017：unknown/stale observation 不是 idle；静默、标题、屏幕文字可作为推断，不能单独证明已消费或确定无副作用。
R-018：rebind 不改变历史作者/请求/消息；旧 epoch 回执保留历史证据但不允许旧实例接收新操作。
R-019：重建 Session 需要配置授权；先恢复最小 ACS 身份、联系人、未读引用和回复规则，不声称恢复了模型工作记忆。
R-020：唤醒是提示，可合并/去重，正文不可被合并丢弃。活动 ToolResult wait 优先交付回复，防止额外 Native 回合；wait 失效后回到 Inbox。

## R-021–R-030：客户端与数据

R-021：通信 conversation 是现有两端消息的可重建查询投影，不是发信前置；默认按 Project 和无序地址对唯一。
R-022：个人 read position 只属于实际 viewer/actor，读取 API 不自动 mark_read，不共享为模型已消费；前进操作单调，手动标未读独立标记。
R-023：snapshot 与 event cursor 在同一一致性边界创建；重连 replay 支持重复和断档，cursor 绑定身份/筛选/授权版本。
R-024：订阅、检索、聚合计数、附件和错误同样复核授权；撤销后不得继续发送正文，缓存失效可明确通知当前连接。
R-025：分页 stable keyset；snapshot 边界固定，后续增量走游标；不可按客户端时钟翻页，不能暴露外域序号推断私信流量。
R-026：正文搜索、附件和原生引用不扩大权限；附件需可信 digest、大小、content type 和传输到接收主机的可达性校验。
R-027：ACS 消息与 native transcript 双源保留 distinct IDs、source、authority、独立 cursor；没有 linkage 不能靠正文相似度去重。
R-028：HTTP 新面与既有 MCP 使用同一领域服务和授权；客户端不能成为较弱入口。
R-029：限制正文、分页、订阅缓冲、并发、重试与附件配额；背压必须可见，不能 ACK 后悄悄丢弃已提交消息。
R-030：事件中字段缺失/unknown 保持未知；UI 不把“未观察”显示成空闲/完成。

## R-031–R-040：实现与交付

R-031：Codex/OpenCode 现有真实 Native 接入保留；支持声明精确到 OS/接入面/版本/授权模式。
R-032：Orca Adapter 使用单一原生输入拥有者，不能与原生 Orchestration 同时投递同一消息。
R-033：完整 UI 清单覆盖数据/操作/事件/降级/测试；原生工具、审批、Diff、模型选择仍由宿主拥有。
R-034：插件 API 不足不以手工 PTY 输入/内部数据库注入冒充完整集成；host gap 明确归类。
R-035：显式迁移、兼容 reader、原消息 checksum/作者/关系不变；默认启动只校验版本。
R-036：恢复操作受权、幂等、有 expected revision、安全准入，失败不自动创建业务 Task 或换人完成。
R-037：诊断最小暴露；日志无凭据/私信正文默认关闭；Manager notice 不包含第三方私信内容。
R-038：真正模型/原生协议/受控 fixture/包自检证据分开；不可把模拟替代真实资格。
R-039：受信接收能力变更必须重新确认；版本、二进制、主机、账号或连接代次变化使旧能力证据失效。
R-040：Core 独立可用，关闭 Orca/UI 后消息持久性、等待恢复和维护器不消失。

这些规则的实现测试映射在 `contracts/requirements.json` 和 `tests/scenarios.json`。不是每个事实都能由 schema 检查；事务、授权和 Native 故障必须在目标系统验证。

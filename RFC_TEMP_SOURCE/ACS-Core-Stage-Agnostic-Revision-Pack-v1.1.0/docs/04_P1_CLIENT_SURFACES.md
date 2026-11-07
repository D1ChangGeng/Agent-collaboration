# 04｜P1 必交：Orca 可用的 ACS 通信服务（不开发 UI）

P1 的“完整”限定为**ACS 负责的通信领域**：可靠查询、操作、实时事件、故障/权限/接收状态、NativeLink 与宿主适配端口。它不意味着复制 Orca 的 transcript、工具、Diff、审批、模型与 Worktree，也不要求已经把 Orca 真正打包发布。

## P1 必需 API

`contracts/api-scope.json` 中标 `P1_required` 的 operationId 必须有真实服务调用和回归：身份/项目/联系人、基于可见消息的 Conversation、原文及回复关联、send/wait、投递和 operation 查询、receiver 能力、受权恢复、系统通知、snapshot/事件回放和 native-link。旧 MCP 与新 HTTP 共享同一 Domain 与权限校验。新增 endpoint 仍必须完成认证、分页/预算、错误副作用、重试、可撤销授权及多项目隔离。不能只以 OpenAPI 声明充数。

P2 的搜索、附件、个人 read-state、偏好、草稿和 notice seen 写入不阻塞 P1；这些端点仍可在 OpenAPI 参考文件中存在，但 `x-acs-tier=P2_optional`，尚未实现时不得发布为可用能力，返回明确未支持，`/meta` 不得声称它们已启用。

## Conversation 不变成新的发送前置

`Conversation = (project_id, authorized participant pair)` 的可重建投影。没有首条消息仍可在 Contacts 中展示潜在通信对象，发送方无需 `createConversation`。Conversation 的排序使用 Authority commit 顺序；消息正文、reply_to、sender 来自原权威表。不能复制出第二套交流事实，也不能把 Native Session ID 当 Conversation ID。

## 事件同步

快照与 event high-water 必须基于一致的权威边界，解决“先查数据、后开始订阅”期间消息丢失窗口。SSE/其他同等可验证订阅支持重复去重、断线 replay、权限撤销、cursor 过期明确 `resync`、慢消费者背压；消息原文一般从受权 read API 获取，事件仅最小 metadata。event journal 可以是现有 Outbox 的读模型或可重建持久投影，不能成为第二消息权威。

P1 不需要模拟“聊天已读”；若不实现个人 read-state，可用基础的新消息提示和连接状态展示，不宣称对端 Agent 已消费，也不以 UI 打开行为改变 Inbox。

## NativeLink + 宿主委托

记录 ACS message_handle 与原生 input/session 的**有证据的、受权关联**，包括 provider/host/session opaque ref 与真实 owner generation；不得靠文本相似性猜关联。Native transcript、工具调用/结果、Diff、审批、模型设置和 Session 控制由 Orca/Harness 的 `NativeViewProvider` 与原始权限拥有。组合视图使用两种独立 cursor 和 provenance；原生输出不能自动生成 ACS 的显式 reply。

`OrcaReceiverPort`/Bridge 是**拟议扩展点**：必须提供清晰的 auth、owner exclusivity、admit/observe/reconcile/unsupported 行为和协议测试。真实 Orca 插件 API 尚无等价公开能力的部分登记 `host_extension_required`；不允许私改 Orca SQLite、抢同一 Session 的 PTY 或利用 Hook 假造确认。真正 `ORCA_HOST_QUALIFIED` 需要独立实机验收。

## P1 最低 headless 客户端链

使用真实 ACS 服务的无 UI consumer：认证/拉取 profile→联系人→无历史会话→发送→读回原文和 reply_to→读 delivery→快照→监听事件→断线 replay/权限撤销→观测 receiver capability→读取诊断/notice→NativeLink 的有证据/缺少宿主时 typed unsupported。模拟的 NativeViewProvider 可测试授权/委托类型，不代表实际 Orca Host 已支持。

**P1 退出**：所有 `P1_required` API/UI 合同、对应 P1 场景及无 UI 客户端通过；Orca native host-qualification 单列，不作为伪“全部接口已实装”。

# 08｜复用现有客户端服务与状态流

## 接口来源

采用当前 ACS 的 `runtime/client_models.schema.json`、`sdk/client-contracts.ts`、`sdk/communication-client.ts` 与实际 OpenAPI。不要把旧开发包里的模型重新生成进客户端，也不要要求开发所有未来可能接口。

Host 持有已授权的 ACS client，renderer 通过现有 preload/RPC 获取投影。已有安全 renderer 数据通路可复用，不强制多加一层中间服务。

## 正常初始化和实时更新

登录/连接 → profile/projects → 选择内部项目 → snapshotView → 读取快照后接续 events → reducer 更新。聊天正文需要时分页/完整读取；不要每个事件都重拉所有 transcript。

使用现有分页 cursor/snapshot、SSE 和 SDK 状态 reducer。消息与 Native 事件各有来源游标，不拼成虚假的全局时间序列。断开重新连接按 SDK 与服务语义恢复，不建立新轮询集群。切换账号/Project 时清理对应视图，不自动重发上一身份未决写操作。

## 各类 UI 的数据源

| UI 行为 | 数据/动作 |
|---|---|
| 联系人/会话列表 | 现有 contacts/conversations；不先创建 Conversation 才允许发信 |
| 发信与回复 | 现有 sendMessage / reply_to；原请求 key 由用户动作一次生成 |
| 历史与搜索 | Messages + literal search；清晰显示搜索作用域 |
| 私人已读/未读 | read-state / notice seen；不消费 Agent Inbox |
| 草稿/偏好 | 对应私人 CAS API；冲突保留可选择文本，不静默覆盖 |
| 通信投递/恢复 | 已有 delivery/operation/receiver actions，友好转译 |
| 查看执行 | readMessage(includeNativeSource) / NativeLink → 现有宿主打开会话/定位 turn |
| 工具、Diff、原生审批 | 原生 session store + 原生 Host 动作 |

## 现有 API 数量不是产品验收指标

35 个操作/30 项合同是参考盘点，不要求给每个操作新建页面；可以多个操作合成一个自然动作。已经完整服务于体验的 API 不再重做。遇到确切缺少的字段，优先在薄投影中补充，不在 Core 添加通用业务模型。

## 写入与回包

UI 可以有“正在发送”的本地呈现，但接到真实 Core receipt 后才显示已发送。写入超时不自动换 key 再发；保留原引用供恢复。这个行为复用已有 SDK，不新增状态机。

原生 Chat 送达与 Agent 的显式 ACS 回复分别显示，用户的个人阅读标记也独立。接收方的最终模型输出可以被观看，但只有对方实际 send_message 才成为 ACS 通信回复。

## 完成条件

用户可在真实应用内找到联系人、向空历史联系人发第一条消息、回复旧消息、搜索并跳到原文、在重开后继续看历史；新消息无需手动刷新；查看执行不要求拷贝 Session ID。全部使用实际 ACS 服务，不使用 fixture-only renderer store。

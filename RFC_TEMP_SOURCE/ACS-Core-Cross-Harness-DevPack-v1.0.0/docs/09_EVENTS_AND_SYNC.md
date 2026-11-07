# 09｜实时事件、快照、游标与个人未读

## 事件承诺

`acs-event/1` 是通信领域的持久事实/投影失效通知，不是完整 Native event stream。每个事件包含 event_id、opaque cursor、project_id、kind、resource_ref、resource_revision、committed_at、auth_revision、payload。默认 payload 只含最小元数据；正文需原 read API 再授权读取。

事件类型见 registry：message.committed/reply.linked/delivery.changed/receiver.observed/capability.changed/notice.created/conversation.updated/read_state.changed/draft.changed/attachment.ready/native_link.changed。控制事件 permission.changed/resync.required/stream.end 不带私信内容，不得用于冒充业务事实。

## Snapshot + subscribe

S1：服务在同一数据库一致性视图读取授权可见 snapshot 与该视图的 event high-water cursor，连同 snapshot_id 和 schema versions 返回。
S2：客户端从 after_cursor 建立 SSE，收到当前 snapshot 之后的事件。不存在“先查列表，后取当前游标”丢事件窗口。
S3：事件至少一次，按 event_id 去重；资源投影只应用较新 revision，旧值/重复不回滚。
S4：网络断开携 Last-Event-ID 重连。HTTP after_cursor 与 header 同时存在必须一致，否则 400。不同 filter/actor/auth revision 的游标拒绝并要求 resnapshot。
S5：保留窗口之外返回 410 cursor_expired/resync.required，不默默从最新开始。客户端重新取 snapshot，保留未发草稿，不悄悄重发 pending command。

事件内部序号可以全 Project 单调，但对外 cursor opaque 且绑定主体和筛选，SSE 不要求 ID 连续（权限过滤可产生内部间隙）。客户端不能把不连续当必然丢失；服务提供 replay boundary/reset 信号。

## 跨流组合

ACS cursor 与 Orca native journal cursor 不可比较。Composite view 每个 source 分别保存恢复点；没有全局时间线顺序承诺。显式 linkage 可把 ACS message 与 native input/turn 关联，视觉时间排序仅 presentation，不改变因果。

## 撤销与并发

emit 前复核当前授权版本。长连接在授权变更时停止私密事件并清理已排队不可见 payload，发最小失效信息后断开。旧游标不能恢复旧权限。网络中断后重新认证；不能靠当前 socket 初始授权永远读取。

已读水位每 (tenant,actor,conversation) 一份逻辑前进状态，设备 revision/CAS 控制 draft 和 preferences。原始 through_message_handle 转换为当前 conversation 的可见 sequence；后到消息不能被一次“全标已读”误覆盖。mark_unread 作为个人 override 与 monotonic frontier 分开，列表计数有精确定义。UI 阅读不引发 Native 接收 ACK，也不能结束 reply wait。

## 缓冲与保留

建议默认每连接缓冲最多 256 个事件或 1 MiB、heartbeat 15 秒、保留窗口 7 天；这是可配置工程预算，不是吞吐 SLA。慢消费者溢出关闭流并要求 replay，不丢已提交事件。message/operation 不随事件 TTL 删除；dedup 保存期必须覆盖配置承诺并在 cleanup 前保留 tombstone，已有 ACS 无固定 TTL 的历史不自动清理。

## MCP 通知

客户端 SSE 不替代 Agent 的 Inbox/wait。可选 MCP resource-change hint 必须映射相同事件事实、遵守工具能力，并且是 hint，不证明消费。无 MCP push 能力的客户端仍可用 bounded wait/read 接续；不得在 Agent prompt 中要求无限轮询。

## 分页快照实现约束

snapshot_id 对应有界、短期的已授权投影快照（建议 TTL 5 分钟），不得持有数据库事务跨客户端网络等待。可以在一致事务内生成分页索引/固定资源 revision，再按该快照读取；如果旧投影不可重建则物化相关页。每页仍重新授权，授权变化使快照失效。过期返回 snapshot_expired；receiver 值是快照时观察，后续变化走事件。不能把“当前最新页”混入旧 snapshot。

未读默认只统计该 conversation 中当前主体收到、尚未越过其阅读水位的 ACS 对端消息；自身发信不增加未读，system notice 单独计数。手动标未读 override 不倒退持久水位。除明确配置默认排序外，不按跨主机 observed_at 计算消息顺序。

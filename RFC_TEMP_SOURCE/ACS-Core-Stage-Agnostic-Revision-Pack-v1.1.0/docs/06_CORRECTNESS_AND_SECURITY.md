# 06｜P0/P1 正确性保证、权限与恢复的不可变契约

## 保证分层（无虚假 exactly-once）

- **已保证的安全目标（P0）**：只有受信作者和受权收件人；持久消息不因 Session 死亡丢失；原文与显式关系不改写；未知 Native 副作用不可盲目再执行；单一原生输入拥有者；未授权操作与读取被拒绝；只读观察不产生 Native 副作用。
- **条件性活性**：在 Receiver 实际可达、授权持续有效、能力受支持、运行时维护器稳定工作的条件下，消息被有界推进或反馈明确阻塞。没有这些前提时不能承诺被模型阅读。
- **不保证**：模型一定理解、推理正确、任务完成、永久离线时送达、没有原生查询/幂等时端到端 exactly-once Native turn。Human approval 不可由普通通信指令冒名替代。

## 保留旧 ACS 的确定语义

1. `send_message` 仍是一种自然消息工具，可用于提问、纠正、交接和回复；`reply_to` 显式关联，第三方不得代答；同对端多引用合法。消息不依赖任务记录。
2. `message_only` 永不因为该消息主动发起 Native，即便 `response_mode=sync`；同步等待和 `wait_for_response` 仅为观察；超时不取消消息或晚到回复。
3. `read_message` 读取不消费历史；UTF-8 byte offset 与 `next_offset=0` 的边界原语保留；同 actor 多 Slot 的真实身份不混淆。
4. Native `dispatch/ack/consumed/turn complete` 与 Agent 显式回复是不同事实；绝不能用原生输出或 UI 读取补造 reply。
5. `list_harnesses` / 其他 list/read 不准备、唤醒或恢复接收端；Project 是通信隔离键，Root/Route 是责任/授权范围，不在新接口下自动拓宽私信可读性。

## 接收端变更与时间问题

Trusted caller、Scope/Grant、receiver current selection、Native owner generation 与 operation ID 均须在最后 handoff 前核对。入站包封存原始 author/recipient/binding/operation；重连后的新 Adapter 不能重新按文本推导 sender。过期 Snapshot/Hook/PTY observation 不能独自支持危险输入。Authoritative time 与不同机器时钟不应被混同。

## 对未确认输入的恢复法则

- 确定未提交到 Provider：可针对**原 operation**重新尝试，在最终 handoff 前再准入；
- 已原生接纳：更新其已接纳证据，不新发一份；
- 未知：只读 reconcile/query 原操作，若无原生查询能力则保留未知、通知合法管理出口、等待受权操作；
- 旧代次 Late ACK：保留对原操作的历史，不得误完成新会话里的 Native handoff；
- 真正对端 reply 已先到：即便 Native ACK 不明，仍可判定回复已经收到，不能推定 Native ACK 也已确认。

技术重试可以是至少一次；**Native 副作用不可因重试产生新的未授权实例**。不能把“我们设了重试次数限制”当成 exactly-once 证明。

## 安全与可见性

HTTP/SSE、MCP、Tool discovery/调用、Source/附件、通知、Manager、Session Host 的授权必须使用相同 Domain 策略。权限撤销后新操作拒绝，长连接停止私密事件；服务端聚合/列表/搜索不能泄漏不可读记录数量。Manager notice 是技术故障提示，不包含第三方私信正文，也不构成回复。日志和导出默认不携敏感正文/凭据。

## 单一原生输入 owner

当 Orca 持有当前 Session，ACS 必须通过受权 Orca Host 端口提交；不能同时用自己的 Driver/PTY 直接输入同一 Native Session。Host 不支持可信输入端口时返回 `host_extension_required`，保持 Inbox，不能通过改 SQLite 或盲键入模拟成功。新的 provider port/bridge 不能强迫所有普通 ACS 客户端安装 Orca。

## 必做负例

未知 ACK 后重放、旧 epoch/旧 process ACK、role downgrade、权限撤销与最后 handoff 竞态、审批与用户 draft 干扰、同 principal 多 Slot、消息转发假 reply、非收件人查询、Project 隔离、`message_only+sync` 的零 Native 副作用，全部需要可复核的测试和证据。缺真实 Harness 可以 `blocked`，不可 synthetic 冒充资格。
